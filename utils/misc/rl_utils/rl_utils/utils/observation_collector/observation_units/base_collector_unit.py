from time import sleep
from typing import Any, Dict

import numpy as np
import rospy
from geometry_msgs.msg import Pose, Pose2D, PoseStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from task_generator.shared import Namespace

from ..constants import OBS_DICT_KEYS, TOPICS, MAX_WAIT, SLEEP
from ..utils import false_params, get_goal_pose_in_robot_frame, pose3d_to_pose2d
from .collector_unit import CollectorUnit


class BaseCollectorUnit(CollectorUnit):
    _robot_state: Odometry
    _robot_pose: Pose2D
    _laser: np.ndarray
    _full_range_laser: np.ndarray
    _subgoal: Pose2D

    def __init__(self, ns: Namespace, observation_manager) -> None:
        super().__init__(ns, observation_manager)
        self._laser_num_beams = rospy.get_param("laser/num_beams")
        self._enable_full_range_laser = rospy.get_param("laser/full_range_laser", False)

        self._robot_state = Odometry()
        self._robot_pose = Pose2D()
        self._laser = np.array([])
        self._full_range_laser = np.array([])
        self._subgoal = Pose2D()

        self._scan_sub: rospy.Subscriber = None
        self._full_scan_sub: rospy.Subscriber = None
        self._robot_state_sub: rospy.Subscriber = None
        self._subgoal_sub: rospy.Subscriber = None

        self._received_odom = False
        self._received_scan = False
        self._received_subgoal = False

        self._first_reset = True

    def init_subs(self):
        self._scan_sub = rospy.Subscriber(
            self._ns(TOPICS.LASER),
            LaserScan,
            self._cb_laser,
            tcp_nodelay=True,
        )
        if self._enable_full_range_laser:
            self._full_scan_sub = rospy.Subscriber(
                self._ns(TOPICS.FULL_RANGE_LASER),
                LaserScan,
                self._cb_full_range_laser,
                tcp_nodelay=True,
            )
        self._robot_state_sub = rospy.Subscriber(
            self._ns(TOPICS.ROBOT_STATE),
            Odometry,
            self._cb_robot_state,
            tcp_nodelay=True,
        )
        self._subgoal_sub = rospy.Subscriber(
            self._ns(TOPICS.GOAL),
            PoseStamped,
            self._cb_subgoal,
            tcp_nodelay=True,
        )

    def wait(self):
        for _ in range(int(MAX_WAIT / SLEEP)):
            if self._received_odom and self._received_scan and self._received_subgoal:
                return

            sleep(SLEEP)

        if self._first_reset:
            self._first_reset = False
            return

        raise TimeoutError(
            f"Couldn't retrieve data for: {false_params(odom=self._received_odom, laser=self._received_scan, subgoal=self._received_subgoal)}"
        )

    def get_observations(
        self, obs_dict: Dict[str, Any], *args, **kwargs
    ) -> Dict[str, Any]:
        if not obs_dict:
            obs_dict = {}

        self.wait()

        dist_to_goal, angle_to_goal = self._process_observations()

        obs_dict.update(
            {
                OBS_DICT_KEYS.LASER: self._laser,
                OBS_DICT_KEYS.ROBOT_POSE: self._robot_pose,
                OBS_DICT_KEYS.GOAL: (dist_to_goal, angle_to_goal),
                OBS_DICT_KEYS.DISTANCE_TO_GOAL: dist_to_goal,
                OBS_DICT_KEYS.LAST_ACTION: kwargs.get(
                    "last_action", np.array([0, 0, 0])
                ),
            }
        )

        if self._enable_full_range_laser:
            obs_dict.update({"full_laser_scan": self._full_range_laser})

        return obs_dict

    def _process_observations(self):
        dist_to_goal, angle_to_goal = get_goal_pose_in_robot_frame(
            goal_pos=self._subgoal, robot_pos=self._robot_pose
        )
        return (
            dist_to_goal,
            angle_to_goal,
        )

    def _cb_laser(self, laser_msg: LaserScan):
        self._received_scan = True
        self._laser = BaseCollectorUnit.process_laser_msg(
            laser_msg=laser_msg, laser_num_beams=self._laser_num_beams
        )

    def _cb_full_range_laser(self, laser_msg: LaserScan):
        self._full_range_laser = BaseCollectorUnit.process_laser_msg(
            laser_msg=laser_msg,
            laser_num_beams=self._laser_num_beams,
        )

    def _cb_robot_state(self, robot_state_msg: Odometry):
        self._received_odom = True
        self._robot_state = robot_state_msg
        self._robot_pose = pose3d_to_pose2d(self._robot_state.pose.pose)

    def _cb_subgoal(self, subgoal_msg: PoseStamped):
        self._received_subgoal = True
        self._subgoal = pose3d_to_pose2d(subgoal_msg.pose)

    @staticmethod
    def process_laser_msg(laser_msg: LaserScan, laser_num_beams: int) -> np.ndarray:
        if len(laser_msg.ranges) == 0:
            return np.zeros(laser_num_beams, dtype=float)

        laser = np.array(laser_msg.ranges, np.float32)
        laser[np.isnan(laser)] = laser_msg.range_max
        return laser

    @staticmethod
    def process_robot_state_msg(pose: Pose) -> Pose2D:
        return pose3d_to_pose2d(pose)
