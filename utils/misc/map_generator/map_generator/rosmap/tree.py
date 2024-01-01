import numpy as np
from ..constants import ROSNAV_PLACEMENT_TRIES


def initialize_map(height: int, width: int, type="indoor") -> np.ndarray:
    # create empty map with format given by height,width and initialize empty tree
    grid_map = np.tile(1, [height, width])
    if type == "outdoor":
        grid_map[slice(1, height - 1), slice(1, width - 1)] = 0
    return grid_map


def insert_root_node(
    grid_map: np.ndarray, tree: list
):  # create root node in center of map
    root_node = [
        int(np.floor(grid_map.shape[0] / 2)),
        int(np.floor(grid_map.shape[1] / 2)),
    ]
    grid_map[root_node[0], root_node[1]] = 0
    tree.append(root_node)


def insert_new_node(
    random_position, tree, map
):  # insert new node into the map and tree
    map[random_position[0], random_position[1]] = 0
    tree.append(random_position)


def sample(grid_map: np.ndarray, corridor_radius: int, map_default: int) -> list:
    # sample position from map within boundary and leave tolerance for corridor width
    # prevent overlapping obstacles
    for _ in range(ROSNAV_PLACEMENT_TRIES):
        random_x = np.random.choice(
            range(corridor_radius + 2, grid_map.shape[0] - corridor_radius - 1)
        )
        random_y = np.random.choice(
            range(corridor_radius + 2, grid_map.shape[1] - corridor_radius - 1)
        )

        sub_grid = grid_map[(random_x - corridor_radius):(random_x + corridor_radius + 1),
                            (random_y - corridor_radius):(random_y + corridor_radius + 1)]
        if np.all(sub_grid == map_default):
            return [random_x, random_y]

    return []


def find_nearest_node(random_position: int, tree: list) -> list:
    # find nearest node according to L1 norm
    nearest_node = []
    min_distance = np.inf
    for node in tree:
        distance = sum(np.abs(np.array(random_position) - np.array(node)))
        if distance < min_distance:
            min_distance = distance
            nearest_node = node
    return nearest_node
