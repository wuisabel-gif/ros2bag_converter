# SPDX-License-Identifier: Apache-2.0
"""ros2bag_converter — decode ROS 2 .db3 bags and export to CSV / JSON.

Public API:
    from ros2bag_converter import decode_message, flatten, open_bag
"""

from .bag import Bag, Topic, open_bag
from .decoder import csv_cell, decode_message, flatten, is_decodable, registry

__version__ = "0.1.0"
__all__ = [
    "open_bag", "Bag", "Topic",
    "decode_message", "flatten", "csv_cell", "is_decodable", "registry",
]
