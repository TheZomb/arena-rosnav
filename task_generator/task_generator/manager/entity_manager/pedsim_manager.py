import dataclasses
import functools
import itertools

import rospy
import re


import pedsim_msgs.msg as pedsim_msgs
from geometry_msgs.msg import Point, Pose, Quaternion
import pedsim_srvs.srv as pedsim_srvs
from std_srvs.srv import SetBool, Trigger


from task_generator.manager.entity_manager.entity_manager import EntityManager
from task_generator.manager.entity_manager.utils import KnownObstacles, SDFUtil, YAMLUtil
from task_generator.constants import Constants, Pedsim
from task_generator.shared import DynamicObstacle, Model, ModelType, Obstacle, PositionOrientation, Robot
from task_generator.simulators.flatland_simulator import FlatlandSimulator

from typing import Iterator, List

from task_generator.simulators.gazebo_simulator import GazeboSimulator
from task_generator.utils import rosparam_get


T = Constants.WAIT_FOR_SERVICE_TIMEOUT

# TODO structure these together


def process_SDF(name: str, base_model: Model) -> Model:
    base_desc = SDFUtil.parse(sdf=base_model.description)
    SDFUtil.set_name(sdf=base_desc, name=name, tag="actor")
    SDFUtil.delete_all(sdf=base_desc, selector=SDFUtil.SFM_PLUGIN_SELECTOR)

    # actor = SDFUtil.get_model_root(base_desc, "actor")

    # assert actor is not None, "# TODO"

    # script = actor.find(r"script")
    # if script is None:
    #     script = ET.SubElement(actor, "script")
    # script.clear()

    # # script_autostart = script.find(r"auto_start")
    # # if script_autostart is None:
    # #     script_autostart = ET.SubElement(script, "auto_start")
    # # script_autostart.text = "false"

    # trajectory = script.find(r"trajectory")
    # if trajectory is None:
    #     trajectory = ET.SubElement(script, "trajectory")
    # trajectory.clear()
    # trajectory.set("id", trajectory.get("id", "0"))
    # trajectory.set("type", trajectory.get("type", "walking"))
    # trajectory.append(ET.fromstring(
    #     "<waypoint><time>0</time><pose>0 0 0 0 0 0</pose></waypoint>"))
    # # trajectory.append(ET.fromstring("<waypoint><time>1</time><pose>0 0 0 0 0 0</pose></waypoint>"))

    pedsim_plugin = base_desc.find(f".//{SDFUtil.PEDSIM_PLUGIN_SELECTOR}")
    if pedsim_plugin is not None:
        pedsim_plugin.set("name", name)

    new_desc = SDFUtil.serialize(base_desc)
    new_model = base_model.replace(description=new_desc)

    return new_model


class PedsimManager(EntityManager):

    _spawn_peds_srv: rospy.ServiceProxy
    _remove_peds_srv: rospy.ServiceProxy
    _reset_peds_srv: rospy.ServiceProxy
    _respawn_obstacles_srv: rospy.ServiceProxy
    _remove_obstacles_srv: rospy.ServiceProxy
    _spawn_obstacles_srv: rospy.ServiceProxy
    _respawn_peds_srv: rospy.ServiceProxy
    _add_walls_srv: rospy.ServiceProxy
    _register_robot_srv: rospy.ServiceProxy

    _known_obstacles: KnownObstacles

    SERVICE_RESET = ""
    
    SERVICE_SPAWN_PEDS = "/pedsim_simulator/spawn_peds"
    SERVICE_MOVE_PEDS = "pedsim_simulator/move_peds"
    SERVICE_RESPAWN_PEDS = "/pedsim_simulator/respawn_peds"
    SERVICE_RESET_ALL_PEDS = "/pedsim_simulator/reset_all_peds"
    SERVICE_REMOVE_ALL_PEDS = "/pedsim_simulator/remove_all_peds"

    SERVICE_ADD_WALLS = "pedsim_simulator/add_walls"
    SERVICE_CLEAR_WALLS = "pedsim_simulator/clear_walls"
    
    SERVICE_SPAWN_OBSTACLES = "pedsim_simulator/spawn_obstacles"
    SERVICE_RESPAWN_OBSTACLES = "pedsim_simulator/respawn_obstacles"
    SERVICE_REMOVE_ALL_OBSTACLES = "pedsim_simulator/remove_all_obstacles"
    
    SERVICE_REGISTER_ROBOT = "pedsim_simulator/register_robot"

    TOPIC_SIMULATED_OBSTACLES = "/pedsim_simulator/simulated_obstacles"
    TOPIC_SIMULATED_PEDS = "/pedsim_simulator/simulated_agents"
    

    def __init__(self, namespace, simulator):

        EntityManager.__init__(self, namespace=namespace, simulator=simulator)

        self._known_obstacles = KnownObstacles()

        rospy.wait_for_service(self.SERVICE_SPAWN_PEDS, timeout=T)
        rospy.wait_for_service(self.SERVICE_RESPAWN_PEDS, timeout=T)
        rospy.wait_for_service(self.SERVICE_RESET_ALL_PEDS, timeout=T)
        rospy.wait_for_service(self.SERVICE_REMOVE_ALL_PEDS, timeout=T)

        rospy.wait_for_service(self.SERVICE_ADD_WALLS, timeout=T)
        rospy.wait_for_service(self.SERVICE_CLEAR_WALLS, timeout=T)

        rospy.wait_for_service(self.SERVICE_SPAWN_OBSTACLES, timeout=T)
        rospy.wait_for_service(self.SERVICE_RESPAWN_OBSTACLES, timeout=T)
        rospy.wait_for_service(self.SERVICE_REMOVE_ALL_OBSTACLES, timeout=T)

        rospy.wait_for_service(self.SERVICE_REGISTER_ROBOT, timeout=T)

        self._spawn_peds_srv = rospy.ServiceProxy(self.SERVICE_SPAWN_PEDS, pedsim_srvs.SpawnPeds, persistent=True)
        self._respawn_peds_srv = rospy.ServiceProxy(self.SERVICE_RESPAWN_PEDS, pedsim_srvs.SpawnPeds, persistent=True)
        self._remove_peds_srv = rospy.ServiceProxy(self.SERVICE_REMOVE_ALL_PEDS, SetBool, persistent=True)
        self._reset_peds_srv = rospy.ServiceProxy(self.SERVICE_RESET_ALL_PEDS, Trigger, persistent=True)
        
        self._spawn_obstacles_srv = rospy.ServiceProxy(self.SERVICE_SPAWN_OBSTACLES, pedsim_srvs.SpawnObstacles, persistent=True)
        self._respawn_obstacles_srv = rospy.ServiceProxy(self.SERVICE_RESPAWN_OBSTACLES, pedsim_srvs.SpawnObstacles, persistent=True)
        self._remove_obstacles_srv = rospy.ServiceProxy(self.SERVICE_REMOVE_ALL_OBSTACLES, Trigger, persistent=True)

        self._add_walls_srv = rospy.ServiceProxy(self.SERVICE_ADD_WALLS, pedsim_srvs.SpawnWalls, persistent=True)
        self._clear_walls_srv = rospy.ServiceProxy(self.SERVICE_CLEAR_WALLS, Trigger, persistent=True)

        self._register_robot_srv = rospy.ServiceProxy(self.SERVICE_REGISTER_ROBOT, pedsim_srvs.RegisterRobot, persistent=True)

        rospy.Subscriber(self.TOPIC_SIMULATED_OBSTACLES, pedsim_msgs.Obstacles, self._obstacle_callback)
        rospy.Subscriber(self.TOPIC_SIMULATED_PEDS, pedsim_msgs.AgentStates, self._ped_callback)

        # temp
        def gen_JAIL_POS(steps: int, x: int = 1, y: int = 0):
            steps = max(steps, 1)
            while True:
                x += y == steps
                y %= steps
                yield (-x, y, 0)
                y += 1
        self.JAIL_POS = gen_JAIL_POS(10)
        # end temp

    def spawn_obstacles(self, obstacles):

        srv = pedsim_srvs.SpawnObstacles()
        srv.InteractiveObstacles = []  # type: ignore

        self.agent_topic_str = ''

        for obstacle in obstacles:
            msg = pedsim_msgs.InteractiveObstacle()

            msg.name = obstacle.name

            # TODO create a global helper function for this kind of use case
            msg.pose = Pose(
                position=Point(
                    x=obstacle.position[0], y=obstacle.position[1], z=0),
                orientation=Quaternion(x=0, y=0, z=obstacle.position[2], w=1)
            )

            interaction_radius: float = obstacle.extra.get(
                "interaction_radius", 0.)

            self.agent_topic_str += f',{obstacle.name}/0'

            msg.type = obstacle.extra.get("type", "")
            msg.interaction_radius = interaction_radius

            msg.yaml_path = obstacle.model.get(ModelType.YAML).path

            srv.InteractiveObstacles.append(msg)  # type: ignore

            known = self._known_obstacles.get(obstacle.name)
            if known is not None:
                if known.obstacle.name != obstacle.name:
                    raise RuntimeError(
                        f"new model name {obstacle.name} does not match model name {known.obstacle.name} of known obstacle {obstacle.name} (did you forget to call remove_obstacles?)")

                known.used = True

            else:
                known = self._known_obstacles.create_or_get(
                    name=obstacle.name,
                    obstacle=obstacle,
                    pedsim_spawned=False,
                    used=True
                )

        max_num_try = 1
        i_curr_try = 0
        rospy.logdebug("trying to call service with interactive obstacles: ")

        while i_curr_try < max_num_try:
            # try to call service
            response = self._respawn_obstacles_srv.call(
                srv.InteractiveObstacles)  # type: ignore

            if not response.success:  # if service not succeeds, do something and redo service
                rospy.logwarn(f"spawn static obstacle failed! trying again... [{i_curr_try+1}/{max_num_try} tried]")
                i_curr_try += 1
            else:
                break
        rospy.set_param(self._namespace(
            "agent_topic_string"), self.agent_topic_str)
        return

    def spawn_dynamic_obstacles(self, obstacles):

        srv = pedsim_srvs.SpawnPeds()
        srv.peds = []  # type: ignore

        self.agent_topic_str = ''

        for obstacle in obstacles:
            msg = pedsim_msgs.Ped()

            msg.id = obstacle.name

            msg.pos = Point(*obstacle.position)

            self.agent_topic_str += f',{obstacle.name}/0'
            msg.type = obstacle.extra.get("type")
            msg.yaml_file = obstacle.model.get(ModelType.YAML).path

            msg.type = "adult"
            msg.number_of_peds = 1
            msg.vmax = Pedsim.VMAX(obstacle.extra.get("vmax", None))
            msg.start_up_mode = Pedsim.START_UP_MODE(
                obstacle.extra.get("start_up_mode", None))
            msg.wait_time = Pedsim.WAIT_TIME(
                obstacle.extra.get("wait_time", None))
            msg.trigger_zone_radius = Pedsim.TRIGGER_ZONE_RADIUS(
                obstacle.extra.get("trigger_zone_radius", None))
            msg.chatting_probability = Pedsim.CHATTING_PROBABILITY(
                obstacle.extra.get("chatting_probability", None))
            msg.tell_story_probability = Pedsim.TELL_STORY_PROBABILITY(
                obstacle.extra.get("tell_story_probability", None))
            msg.group_talking_probability = Pedsim.GROUP_TALKING_PROBABILITY(
                obstacle.extra.get("group_talking_probability", None))
            msg.talking_and_walking_probability = Pedsim.TALKING_AND_WALKING_PROBABILITY(
                obstacle.extra.get("talking_and_walking_probability", None))
            msg.requesting_service_probability = Pedsim.REQUESTING_SERVICE_PROBABILITY(
                obstacle.extra.get("requesting_service_probability", None))
            msg.requesting_guide_probability = Pedsim.REQUESTING_GUIDE_PROBABILITY(
                obstacle.extra.get("requesting_guide_probability", None))
            msg.requesting_follower_probability = Pedsim.REQUESTING_FOLLOWER_PROBABILITY(
                obstacle.extra.get("requesting_follower_probability", None))
            msg.max_talking_distance = Pedsim.MAX_TALKING_DISTANCE(
                obstacle.extra.get("max_talking_distance", None))
            msg.max_servicing_radius = Pedsim.MAX_SERVICING_RADIUS(
                obstacle.extra.get("max_servicing_radius", None))
            msg.talking_base_time = Pedsim.TALKING_BASE_TIME(
                obstacle.extra.get("talking_base_time", None))
            msg.tell_story_base_time = Pedsim.TELL_STORY_BASE_TIME(
                obstacle.extra.get("tell_story_base_time", None))
            msg.group_talking_base_time = Pedsim.GROUP_TALKING_BASE_TIME(
                obstacle.extra.get("group_talking_base_time", None))
            msg.talking_and_walking_base_time = Pedsim.TALKING_AND_WALKING_BASE_TIME(
                obstacle.extra.get("talking_and_walking_base_time", None))
            msg.receiving_service_base_time = Pedsim.RECEIVING_SERVICE_BASE_TIME(
                obstacle.extra.get("receiving_service_base_time", None))
            msg.requesting_service_base_time = Pedsim.REQUESTING_SERVICE_BASE_TIME(
                obstacle.extra.get("requesting_service_base_time", None))
            msg.force_factor_desired = Pedsim.FORCE_FACTOR_DESIRED(
                obstacle.extra.get("force_factor_desired", None))
            msg.force_factor_obstacle = Pedsim.FORCE_FACTOR_OBSTACLE(
                obstacle.extra.get("force_factor_obstacle", None))
            msg.force_factor_social = Pedsim.FORCE_FACTOR_SOCIAL(
                obstacle.extra.get("force_factor_social", None))
            msg.force_factor_robot = Pedsim.FORCE_FACTOR_ROBOT(
                obstacle.extra.get("force_factor_robot", None))
            msg.waypoint_mode = Pedsim.WAYPOINT_MODE(
                obstacle.extra.get("waypoint_mode", None))

            msg.waypoints = [Point(*waypoint) for waypoint in obstacle.waypoints]

            srv.peds.append(msg)  # type: ignore

            obstacle = dataclasses.replace(
                obstacle,
                model=obstacle.model
                .override(
                    model_type=ModelType.SDF,
                    override=functools.partial(
                        process_SDF, str(msg.id)),
                    name=msg.id
                )
                .override(
                    model_type=ModelType.YAML,
                    override=lambda model: model.replace(
                        description=YAMLUtil.serialize(
                            YAMLUtil.update_plugins(
                                namespace=self._simulator._namespace(
                                    str(msg.id)),
                                description=YAMLUtil.parse_yaml(
                                    model.description)
                            )
                        )
                    ),
                    name=msg.id
                )
            )

            known = self._known_obstacles.get(msg.id)
            if known is not None:
                if known.obstacle.name != obstacle.name:
                    raise RuntimeError(
                        f"new model name {obstacle.name} does not match model name {known.obstacle.name} of known obstacle {msg.id} (did you forget to call remove_obstacles?)")

                known.used = True
            else:
                known = self._known_obstacles.create_or_get(
                    name=msg.id,
                    obstacle=obstacle,
                    pedsim_spawned=False,
                    used=True
                )

        max_num_try = 1
        i_curr_try = 0
        while i_curr_try < max_num_try:
            # try to call service
            response = self._respawn_peds_srv.call(srv.peds)  # type: ignore

            if not response.success:  # if service not succeeds, do something and redo service
                rospy.logwarn(f"spawn human failed! trying again... [{i_curr_try+1}/{max_num_try} tried]")
                i_curr_try += 1
            else:
                break

        rospy.set_param(self._namespace(
            "agent_topic_string"), self.agent_topic_str)
        rospy.set_param("respawn_dynamic", True)

    def spawn_line_obstacle(self, name, _from, _to):
        return

    def unuse_obstacles(self):
        for obstacle in self._known_obstacles.values():
            obstacle.used = False

    def remove_obstacles(self, purge):
        to_forget: List[str] = list()

        for obstacle_id, obstacle in self._known_obstacles.items():
            if purge or not obstacle.used:

                if isinstance(self._simulator, GazeboSimulator):
                    # TODO remove this once actors can be deleted properly
                    if isinstance(obstacle.obstacle, DynamicObstacle):
                        jail = next(self.JAIL_POS)
                        self._simulator.move_entity(name=obstacle_id, position=jail)
                    else:
                    # end
                        self._simulator.delete_entity(name=obstacle_id)

                obstacle.pedsim_spawned = False
                obstacle.used = False
                to_forget.append(obstacle_id)

        for obstacle_id in to_forget:
            self._known_obstacles.forget(name=obstacle_id)


    def _obstacle_callback(self, obstacles: pedsim_msgs.Obstacles):
        if isinstance(self._simulator, FlatlandSimulator):
            return # already taken care of by pedsim

        for obstacle in (obstacles.obstacles or []):
            self._respawn_obstacle(obstacle)

    def _ped_callback(self, actors: pedsim_msgs.AgentStates):
        if isinstance(self._simulator, FlatlandSimulator):
            return # already taken care of by pedsim

        agent_states: List[pedsim_msgs.AgentState] = actors.agent_states or []

        for actor in agent_states:

            actor_id = str(actor.id)

            obstacle = self._known_obstacles.get(actor_id)

            if obstacle is None:
                rospy.logwarn(
                    f"dynamic obstacle {actor_id} not known by {type(self).__name__}")
                continue

            actor_pose = actor.pose

            if obstacle.pedsim_spawned:
                pass  # handled by pedsim
                # self._simulator.move_entity(
                #     name=actor_id,
                #     position=(
                #         actor_pose.position.x,
                #         actor_pose.position.y,
                #         actor_pose.orientation.z
                #     )
                # )

            else:
                rospy.logdebug(
                    "Spawning dynamic obstacle: actor_id = %s", actor_id)

                self._simulator.spawn_entity(
                    entity=Obstacle(
                        name=actor_id,
                        position=(
                            actor_pose.position.x,
                            actor_pose.position.y,
                            actor_pose.orientation.z
                        ),
                        model=obstacle.obstacle.model,
                        extra=obstacle.obstacle.extra
                    )
                )

                obstacle.pedsim_spawned = True

    def _respawn_obstacle(self, obstacle: pedsim_msgs.Obstacle):

        obstacle_name = obstacle.name

        entity = self._known_obstacles.get(obstacle_name)

        if entity is None:
            # rospy.logwarn(
            #     f"obstacle {obstacle_name} not known by {type(self).__name__} (known: {list(self._known_obstacles.keys())})")
            return

        if entity.pedsim_spawned == True:
            return

        if entity.pedsim_spawned:
            self._simulator.move_entity(
                position=(
                    obstacle.pose.position.x,
                    obstacle.pose.position.y,
                    obstacle.pose.orientation.z
                ),
                name=obstacle_name
            )

        else:
            rospy.logdebug("Spawning obstacle: name = %s", obstacle_name)

            self._simulator.spawn_entity(
                Obstacle(
                    name=obstacle_name,
                    position=(
                        obstacle.pose.position.x,
                        obstacle.pose.position.y,
                        obstacle.pose.orientation.z
                    ),
                    model=entity.obstacle.model,
                    extra=entity.obstacle.extra
                )
            )

            entity.pedsim_spawned = True

    def spawn_robot(self, robot: Robot):
        self._simulator.spawn_entity(robot)

        request = pedsim_srvs.RegisterRobotRequest()

        request.name = robot.name
        request.odom_topic = self._namespace(robot.name, "odom")

        self._register_robot_srv(request)

    def move_robot(self, name: str, position: PositionOrientation):
        self._simulator.move_entity(name=name, position=position)
