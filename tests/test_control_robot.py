"""
Tests for physical robots and their mocked versions.
If the physical robots are not connected to the computer, or not working,
the test will be skipped.

Example of running a specific test:
```bash
pytest -sx tests/test_control_robot.py::test_teleoperate
```

Example of running test on real robots connected to the computer:
```bash
pytest -sx 'tests/test_control_robot.py::test_teleoperate[koch-False]'
pytest -sx 'tests/test_control_robot.py::test_teleoperate[koch_bimanual-False]'
pytest -sx 'tests/test_control_robot.py::test_teleoperate[aloha-False]'
```

Example of running test on a mocked version of robots:
```bash
pytest -sx 'tests/test_control_robot.py::test_teleoperate[koch-True]'
pytest -sx 'tests/test_control_robot.py::test_teleoperate[koch_bimanual-True]'
pytest -sx 'tests/test_control_robot.py::test_teleoperate[aloha-True]'
```
"""

import multiprocessing
from pathlib import Path
from unittest.mock import patch

import pytest

from lerobot.common.logger import Logger
from lerobot.common.policies.act.configuration_act import ACTConfig
from lerobot.common.policies.factory import make_policy
from lerobot.common.robot_devices.control_configs import (
    CalibrateControlConfig,
    RecordControlConfig,
    ReplayControlConfig,
    TeleoperateControlConfig,
)
from lerobot.configs.default import DatasetConfig
from lerobot.configs.policies import PreTrainedConfig
from lerobot.configs.train import TrainPipelineConfig
from lerobot.scripts.control_robot import calibrate, record, replay, teleoperate
from tests.test_robots import make_robot
from tests.utils import DEVICE, TEST_ROBOT_TYPES, mock_calibration_dir, require_robot


@pytest.mark.parametrize("robot_type, mock", TEST_ROBOT_TYPES)
@require_robot
def test_teleoperate(tmpdir, request, robot_type, mock):
    robot_kwargs = {"robot_type": robot_type, "mock": mock}

    if mock and robot_type != "aloha":
        request.getfixturevalue("patch_builtins_input")

        # Create an empty calibration directory to trigger manual calibration
        # and avoid writing calibration files in user .cache/calibration folder
        tmpdir = Path(tmpdir)
        calibration_dir = tmpdir / robot_type
        mock_calibration_dir(calibration_dir)
        robot_kwargs["calibration_dir"] = calibration_dir
    else:
        # Use the default .cache/calibration folder when mock=False
        pass

    robot = make_robot(**robot_kwargs)
    teleoperate(robot, TeleoperateControlConfig(teleop_time_s=1))
    teleoperate(robot, TeleoperateControlConfig(fps=30, teleop_time_s=1))
    teleoperate(robot, TeleoperateControlConfig(fps=60, teleop_time_s=1))
    del robot


@pytest.mark.parametrize("robot_type, mock", TEST_ROBOT_TYPES)
@require_robot
def test_calibrate(tmpdir, request, robot_type, mock):
    robot_kwargs = {"robot_type": robot_type, "mock": mock}

    if mock:
        request.getfixturevalue("patch_builtins_input")

    # Create an empty calibration directory to trigger manual calibration
    tmpdir = Path(tmpdir)
    calibration_dir = tmpdir / robot_type
    robot_kwargs["calibration_dir"] = calibration_dir

    robot = make_robot(**robot_kwargs)
    calib_cfg = CalibrateControlConfig(arms=robot.available_arms)
    calibrate(robot, calib_cfg)
    del robot


@pytest.mark.parametrize("robot_type, mock", TEST_ROBOT_TYPES)
@require_robot
def test_record_without_cameras(tmpdir, request, robot_type, mock):
    robot_kwargs = {"robot_type": robot_type, "mock": mock}

    # Avoid using cameras
    robot_kwargs["cameras"] = {}

    if mock and robot_type != "aloha":
        request.getfixturevalue("patch_builtins_input")

        # Create an empty calibration directory to trigger manual calibration
        # and avoid writing calibration files in user .cache/calibration folder
        calibration_dir = Path(tmpdir) / robot_type
        mock_calibration_dir(calibration_dir)
        robot_kwargs["calibration_dir"] = calibration_dir
    else:
        # Use the default .cache/calibration folder when mock=False
        pass

    repo_id = "lerobot/debug"
    root = Path(tmpdir) / "data" / repo_id
    single_task = "Do something."

    robot = make_robot(**robot_kwargs)
    rec_cfg = RecordControlConfig(
        repo_id=repo_id,
        single_task=single_task,
        root=root,
        fps=30,
        warmup_time_s=0.1,
        episode_time_s=1,
        reset_time_s=0.1,
        num_episodes=2,
        run_compute_stats=False,
        push_to_hub=False,
        video=False,
        play_sounds=False,
    )
    record(robot, rec_cfg)


@pytest.mark.parametrize("robot_type, mock", TEST_ROBOT_TYPES)
@require_robot
def test_record_and_replay_and_policy(tmpdir, request, robot_type, mock):
    tmpdir = Path(tmpdir)
    robot_kwargs = {"robot_type": robot_type, "mock": mock}

    if mock and robot_type != "aloha":
        request.getfixturevalue("patch_builtins_input")

        # Create an empty calibration directory to trigger manual calibration
        # and avoid writing calibration files in user .cache/calibration folder
        calibration_dir = tmpdir / robot_type
        mock_calibration_dir(calibration_dir)
        robot_kwargs["calibration_dir"] = calibration_dir
    else:
        # Use the default .cache/calibration folder when mock=False
        pass

    repo_id = "lerobot_test/debug"
    root = tmpdir / "data" / repo_id
    single_task = "Do something."

    robot = make_robot(**robot_kwargs)
    rec_cfg = RecordControlConfig(
        repo_id=repo_id,
        single_task=single_task,
        root=root,
        fps=1,
        warmup_time_s=0.1,
        episode_time_s=1,
        reset_time_s=0.1,
        num_episodes=2,
        push_to_hub=False,
        # TODO(rcadene, aliberts): test video=True
        video=False,
        # TODO(rcadene): display cameras through cv2 sometimes crashes on mac
        display_cameras=False,
        play_sounds=False,
    )
    dataset = record(robot, rec_cfg)
    assert dataset.meta.total_episodes == 2
    assert len(dataset) == 2

    replay_cfg = ReplayControlConfig(
        episode=0, fps=1, root=root, repo_id=repo_id, play_sounds=False, local_files_only=True
    )
    replay(robot, replay_cfg)

    policy_cfg = ACTConfig()
    policy = make_policy(policy_cfg, ds_meta=dataset.meta, device=DEVICE)

    out_dir = tmpdir / "logger"

    ds_cfg = DatasetConfig(repo_id, local_files_only=True)
    train_cfg = TrainPipelineConfig(
        dataset=ds_cfg,
        policy=policy_cfg,
        output_dir=out_dir,
        device=DEVICE,
    )
    logger = Logger(train_cfg)
    logger.save_checkpoint(
        train_step=0,
        identifier=0,
        policy=policy,
    )
    pretrained_policy_path = out_dir / "checkpoints/last/pretrained_model"

    # In `examples/9_use_aloha.md`, we advise using `num_image_writer_processes=1`
    # during inference, to reach constent fps, so we test this here.
    if robot_type == "aloha":
        num_image_writer_processes = 1

        # `multiprocessing.set_start_method("spawn", force=True)` avoids a hanging issue
        # before exiting pytest. However, it outputs the following error in the log:
        # Traceback (most recent call last):
        #     File "<string>", line 1, in <module>
        #     File "/Users/rcadene/miniconda3/envs/lerobot/lib/python3.10/multiprocessing/spawn.py", line 116, in spawn_main
        #         exitcode = _main(fd, parent_sentinel)
        #     File "/Users/rcadene/miniconda3/envs/lerobot/lib/python3.10/multiprocessing/spawn.py", line 126, in _main
        #         self = reduction.pickle.load(from_parent)
        #     File "/Users/rcadene/miniconda3/envs/lerobot/lib/python3.10/multiprocessing/synchronize.py", line 110, in __setstate__
        #         self._semlock = _multiprocessing.SemLock._rebuild(*state)
        # FileNotFoundError: [Errno 2] No such file or directory
        # TODO(rcadene, aliberts): fix FileNotFoundError in multiprocessing
        multiprocessing.set_start_method("spawn", force=True)
    else:
        num_image_writer_processes = 0

    eval_repo_id = "lerobot/eval_debug"
    eval_root = tmpdir / "data" / eval_repo_id

    rec_eval_cfg = RecordControlConfig(
        repo_id=eval_repo_id,
        root=eval_root,
        single_task=single_task,
        fps=1,
        warmup_time_s=0.1,
        episode_time_s=1,
        reset_time_s=0.1,
        num_episodes=2,
        run_compute_stats=False,
        push_to_hub=False,
        video=False,
        display_cameras=False,
        play_sounds=False,
        num_image_writer_processes=num_image_writer_processes,
        device=DEVICE,
        use_amp=False,
    )

    rec_eval_cfg.policy = PreTrainedConfig.from_pretrained(pretrained_policy_path)
    rec_eval_cfg.policy.pretrained_path = pretrained_policy_path

    dataset = record(robot, rec_eval_cfg)
    assert dataset.num_episodes == 2
    assert len(dataset) == 2

    del robot


@pytest.mark.parametrize("robot_type, mock", [("koch", True)])
@require_robot
def test_resume_record(tmpdir, request, robot_type, mock):
    robot_kwargs = {"robot_type": robot_type, "mock": mock}

    if mock and robot_type != "aloha":
        request.getfixturevalue("patch_builtins_input")

        # Create an empty calibration directory to trigger manual calibration
        # and avoid writing calibration files in user .cache/calibration folder
        calibration_dir = tmpdir / robot_type
        mock_calibration_dir(calibration_dir)
        robot_kwargs["calibration_dir"] = calibration_dir
    else:
        # Use the default .cache/calibration folder when mock=False
        pass

    robot = make_robot(**robot_kwargs)

    repo_id = "lerobot/debug"
    root = Path(tmpdir) / "data" / repo_id
    single_task = "Do something."

    rec_cfg = RecordControlConfig(
        repo_id=repo_id,
        root=root,
        single_task=single_task,
        fps=1,
        warmup_time_s=0,
        episode_time_s=1,
        push_to_hub=False,
        video=False,
        display_cameras=False,
        play_sounds=False,
        run_compute_stats=False,
        local_files_only=True,
        num_episodes=1,
    )

    dataset = record(robot, rec_cfg)
    assert len(dataset) == 1, f"`dataset` should contain 1 frame, not {len(dataset)}"

    with pytest.raises(FileExistsError):
        # Dataset already exists, but resume=False by default
        record(robot, rec_cfg)

    rec_cfg.resume = True
    dataset = record(robot, rec_cfg)
    assert len(dataset) == 2, f"`dataset` should contain 2 frames, not {len(dataset)}"


@pytest.mark.parametrize("robot_type, mock", [("koch", True)])
@require_robot
def test_record_with_event_rerecord_episode(tmpdir, request, robot_type, mock):
    robot_kwargs = {"robot_type": robot_type, "mock": mock}

    if mock and robot_type != "aloha":
        request.getfixturevalue("patch_builtins_input")

        # Create an empty calibration directory to trigger manual calibration
        # and avoid writing calibration files in user .cache/calibration folder
        calibration_dir = tmpdir / robot_type
        mock_calibration_dir(calibration_dir)
        robot_kwargs["calibration_dir"] = calibration_dir
    else:
        # Use the default .cache/calibration folder when mock=False
        pass

    robot = make_robot(**robot_kwargs)

    with patch("lerobot.scripts.control_robot.init_keyboard_listener") as mock_listener:
        mock_events = {}
        mock_events["exit_early"] = True
        mock_events["rerecord_episode"] = True
        mock_events["stop_recording"] = False
        mock_listener.return_value = (None, mock_events)

        repo_id = "lerobot/debug"
        root = Path(tmpdir) / "data" / repo_id
        single_task = "Do something."

        rec_cfg = RecordControlConfig(
            repo_id=repo_id,
            root=root,
            single_task=single_task,
            fps=1,
            warmup_time_s=0,
            episode_time_s=1,
            num_episodes=1,
            push_to_hub=False,
            video=False,
            display_cameras=False,
            play_sounds=False,
            run_compute_stats=False,
        )
        dataset = record(robot, rec_cfg)

        assert not mock_events["rerecord_episode"], "`rerecord_episode` wasn't properly reset to False"
        assert not mock_events["exit_early"], "`exit_early` wasn't properly reset to False"
        assert len(dataset) == 1, "`dataset` should contain only 1 frame"


@pytest.mark.parametrize("robot_type, mock", [("koch", True)])
@require_robot
def test_record_with_event_exit_early(tmpdir, request, robot_type, mock):
    robot_kwargs = {"robot_type": robot_type, "mock": mock}

    if mock:
        request.getfixturevalue("patch_builtins_input")

        # Create an empty calibration directory to trigger manual calibration
        # and avoid writing calibration files in user .cache/calibration folder
        calibration_dir = tmpdir / robot_type
        mock_calibration_dir(calibration_dir)
        robot_kwargs["calibration_dir"] = calibration_dir
    else:
        # Use the default .cache/calibration folder when mock=False
        pass

    robot = make_robot(**robot_kwargs)

    with patch("lerobot.scripts.control_robot.init_keyboard_listener") as mock_listener:
        mock_events = {}
        mock_events["exit_early"] = True
        mock_events["rerecord_episode"] = False
        mock_events["stop_recording"] = False
        mock_listener.return_value = (None, mock_events)

        repo_id = "lerobot/debug"
        root = Path(tmpdir) / "data" / repo_id
        single_task = "Do something."

        rec_cfg = RecordControlConfig(
            repo_id=repo_id,
            root=root,
            single_task=single_task,
            fps=2,
            warmup_time_s=0,
            episode_time_s=1,
            num_episodes=1,
            push_to_hub=False,
            video=False,
            display_cameras=False,
            play_sounds=False,
            run_compute_stats=False,
        )

        dataset = record(robot, rec_cfg)

        assert not mock_events["exit_early"], "`exit_early` wasn't properly reset to False"
        assert len(dataset) == 1, "`dataset` should contain only 1 frame"


@pytest.mark.parametrize(
    "robot_type, mock, num_image_writer_processes", [("koch", True, 0), ("koch", True, 1)]
)
@require_robot
def test_record_with_event_stop_recording(tmpdir, request, robot_type, mock, num_image_writer_processes):
    robot_kwargs = {"robot_type": robot_type, "mock": mock}

    if mock:
        request.getfixturevalue("patch_builtins_input")

        # Create an empty calibration directory to trigger manual calibration
        # and avoid writing calibration files in user .cache/calibration folder
        calibration_dir = tmpdir / robot_type
        mock_calibration_dir(calibration_dir)
        robot_kwargs["calibration_dir"] = calibration_dir
    else:
        # Use the default .cache/calibration folder when mock=False
        pass

    robot = make_robot(**robot_kwargs)

    with patch("lerobot.scripts.control_robot.init_keyboard_listener") as mock_listener:
        mock_events = {}
        mock_events["exit_early"] = True
        mock_events["rerecord_episode"] = False
        mock_events["stop_recording"] = True
        mock_listener.return_value = (None, mock_events)

        repo_id = "lerobot/debug"
        root = Path(tmpdir) / "data" / repo_id
        single_task = "Do something."

        rec_cfg = RecordControlConfig(
            repo_id=repo_id,
            root=root,
            single_task=single_task,
            fps=1,
            warmup_time_s=0,
            episode_time_s=1,
            reset_time_s=0.1,
            num_episodes=2,
            push_to_hub=False,
            video=False,
            display_cameras=False,
            play_sounds=False,
            run_compute_stats=False,
            num_image_writer_processes=num_image_writer_processes,
        )

        dataset = record(robot, rec_cfg)

        assert not mock_events["exit_early"], "`exit_early` wasn't properly reset to False"
        assert len(dataset) == 1, "`dataset` should contain only 1 frame"
