import os
import random
from typing import Any, List, Type

from habitat import Config, ThreadedVectorEnv, VectorEnv, logger, make_dataset
from habitat.utils.gym_definitions import make_gym_from_config


def construct_envs(
    config: Config,
    workers_ignore_signals: bool = False,
    enforce_scenes_greater_eq_environments: bool = False,
) -> VectorEnv:
    r"""Create VectorEnv object with specified config and env class type.
    To allow better performance, dataset are split into small ones for
    each individual env, grouped by scenes.

    :param config: configs that contain num_environments as well as information
    :param necessary to create individual environments.
    :param workers_ignore_signals: Passed to :ref:`habitat.VectorEnv`'s constructor
    :param enforce_scenes_greater_eq_environments: Make sure that there are more (or equal)
        scenes than environments. This is needed for correct evaluation.

    :return: VectorEnv object created according to specification.
    """

    num_environments = config.num_environments
    configs = []
    dataset = make_dataset(config.habitat.dataset.type)
    scenes = config.habitat.dataset.content_scenes
    if "*" in config.habitat.dataset.content_scenes:
        scenes = dataset.get_scenes_to_load(config.habitat.dataset)

    if num_environments < 1:
        raise RuntimeError("num_environments must be strictly positive")

    if len(scenes) == 0:
        raise RuntimeError(
            "No scenes to load, multiple process logic relies on being able to split scenes uniquely between processes"
        )

    random.shuffle(scenes)

    scene_splits: List[List[str]] = [[] for _ in range(num_environments)]
    if len(scenes) < num_environments:
        msg = f"There are less scenes ({len(scenes)}) than environments ({num_environments}). "
        if enforce_scenes_greater_eq_environments:
            logger.warn(
                msg
                + "Reducing the number of environments to be the number of scenes."
            )
            num_environments = len(scenes)
            scene_splits = [[s] for s in scenes]
        else:
            logger.warn(
                msg
                + "Each environment will use all the scenes instead of using a subset."
            )
        for scene in scenes:
            for split in scene_splits:
                split.append(scene)
    else:
        for idx, scene in enumerate(scenes):
            scene_splits[idx % len(scene_splits)].append(scene)
        assert sum(map(len, scene_splits)) == len(scenes)

    for i in range(num_environments):
        proc_config = config.clone()
        proc_config.defrost()

        task_config = proc_config.habitat
        task_config.seed = task_config.seed + i
        if len(scenes) > 0:
            task_config.dataset.content_scenes = scene_splits[i]

        task_config.simulator.habitat_sim_v0.gpu_device_id = (
            config.simulator_gpu_id
        )

        task_config.simulator.agent_0.sensors = config.sensors

        proc_config.freeze()
        configs.append(proc_config)

    vector_env_cls: Type[Any]
    if int(os.environ.get("HABITAT_ENV_DEBUG", 0)):
        logger.warn(
            "Using the debug Vector environment interface. Expect slower performance."
        )
        vector_env_cls = ThreadedVectorEnv
    else:
        vector_env_cls = VectorEnv

    envs = vector_env_cls(
        make_env_fn=make_gym_from_config,
        env_fn_args=tuple((c,) for c in configs),
        workers_ignore_signals=workers_ignore_signals,
    )
    return envs
