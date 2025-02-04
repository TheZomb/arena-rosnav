import rospy
from task_generator.shared import DynamicObstacle, Namespace, Obstacle, PositionOrientation, Robot
from task_generator.simulators.base_simulator import BaseSimulator
from typing import Collection
from geometry_msgs.msg import Point, PoseStamped
from task_generator.utils import rosparam_get


class EntityManager:

    _namespace: Namespace
    _simulator: BaseSimulator

    _robot_name: str
    _goal_pub: rospy.Publisher

    def __init__(self, namespace: Namespace, simulator: BaseSimulator):
        """
            Initialize dynamic obstacle manager.

            @namespace: global namespace
            @simulator: Simulator instance
        """

        self._simulator = simulator
        self._namespace = namespace

        self._goal_pub = rospy.Publisher(self._namespace(
            "/goal"), PoseStamped, queue_size=1, latch=True)

        self._robot_name = rosparam_get(str, "robot_model", "")

        self._spawned_obstacles = []
        self._namespaces = dict()

    def spawn_obstacles(self, obstacles: Collection[Obstacle]):
        """
        Loads given obstacles into the simulator. 
        If the object has an interaction radius of > 0, 
        then load it as an interactive obstacle instead of static
        """
        raise NotImplementedError()

    def spawn_dynamic_obstacles(self, obstacles: Collection[DynamicObstacle]):
        """
        Loads given obstacles into the simulator.
        Currently by loading a existing sdf file, 
        then reaplacing the static values by dynamic ones 
        """

    def spawn_line_obstacle(self, name: str, _from: Point, _to: Point):
        """
        Creates a line obstacle.
        """
        raise NotImplementedError()

    def unuse_obstacles(self):
        """
        Prepares obstacles for reuse or removal.
        """
        raise NotImplementedError()

    def remove_obstacles(self, purge: bool = True):
        """
        Removes obstacles from simulator.
        @purge: if False, only remove unused obstacles
        """
        raise NotImplementedError()

    def spawn_robot(self, robot: Robot):
        """
        Spawns a robot.
        @robot: Robot description.
        """
        raise NotImplementedError()

    def move_robot(self, name: str, position: PositionOrientation):
        """
        Moves a robot.
        @name: Robot name
        @position: Target position
        """
        raise NotImplementedError()
