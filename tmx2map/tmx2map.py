"""Command line utility for creating and creating WAD files from BSP files

Supported Tilemaps:
    - Tiled

Supported Games:
    - QUAKE
"""

import argparse
import json
import os
import sys
import time

import numpy
import tmx
from quake import map as m

import mathhelper


class ResolvePathAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if isinstance(values, list):
            fullpath = [os.path.expanduser(v) for v in values]
        else:
            fullpath = os.path.expanduser(values)

        setattr(namespace, self.dest, fullpath)


class Parser(argparse.ArgumentParser):
    """Simple wrapper class to provide help on error"""
    def error(self, message):
        sys.stderr.write('error: %s\n' % message)
        self.print_help()
        sys.exit(1)


parser = Parser(prog='tmx2map',
                description='Default action is to create a map file from a tmx tilemap',
                epilog='example: tmx2map {0} {1} => creates the map file {2}'.format('e1m1.tmx', 'mapping.json', 'e1m1.map'))

parser.add_argument('tilemap_file',
                    metavar='file.tmx',
                    action=ResolvePathAction,
                    help='Tiled tilemap file')

parser.add_argument('mapping_file',
                    metavar='mapping.json',
                    action=ResolvePathAction,
                    help='json tile mapping file')

parser.add_argument('-d',
                    metavar='file.map',
                    dest='dest',
                    default=os.getcwd(),
                    action=ResolvePathAction,
                    help='name of created map file')

parser.add_argument('-q',
                    dest='quiet',
                    action='store_true',
                    help='quiet mode')

args = parser.parse_args()

start_time = time.time()
step_timing = [0]


def record_step_time():
    delta = time.time() - start_time - step_timing[-1]
    step_timing.append(delta)
    print('{:5.4f} seconds'.format(step_timing[-1]))
    print()

print('Loading 2D tilemap...')
# Load the tilemap
tmx_file = tmx.TileMap.load(args.tilemap_file)

tilesets_2d_found = len(tmx_file.tilesets)
print('{} 2D tileset{} found'.format(str(tilesets_2d_found).rjust(6), 's' if tilesets_2d_found > 1 else ''))

# Resolve path to map file
if args.dest == os.getcwd():
    map_path = os.path.dirname(args.tilemap_file)
    map_name = os.path.basename(args.tilemap_file).split('.')[0] + '.map'
    args.dest = os.path.join(map_path, map_name)

# Create the file path if needed
dir = os.path.dirname(args.dest) or '.'
if not os.path.exists(dir):
    os.makedirs(dir)

# Get full path to mappings file
cwd = os.getcwd()
args.mapping_file = os.path.normpath(os.path.join(cwd, args.mapping_file))

filepath = args.tilemap_file
tilemap = tmx.TileMap.load(filepath)

width = tilemap.width
height = tilemap.height

record_step_time()

print('Loading 3D tiles...')
with open(args.mapping_file) as file:
    tile_mapping = json.loads(file.read())

# Loading in the 3D tile data
tiles = {}
tile_size_3d = tile_mapping["tilesize"]
tile_size_2d = tilemap.width

tilemap_width_3d = tilemap.width * tile_size_3d
tilemap_height_3d = tilemap.height * tile_size_3d

if tilemap_width_3d > 8192:
    print('WARNING: Map x dimensions exceeds +-4096 limit.')

if tilemap_height_3d > 8192:
    print('WARNING: Map y dimensions exceeds +-4096 limit.')

tilesets_3d_found = len(tile_mapping["tilesets"])

for tileset in tile_mapping["tilesets"]:
    filename = tileset["filename"]

    # Grab the tileset def from the tilemap
    tileset_definition = [t for t in tilemap.tilesets if os.path.basename(t.image.source) == filename]
    if not tileset_definition:
        continue

    tileset_definition = tileset_definition[0]
    tile_count = tileset_definition.tilecount
    first_gid = tileset_definition.firstgid

    for tile_id in tileset["tiles"]:
        gid = int(tile_id) + first_gid
        tile_filename = tileset["tiles"][tile_id]

        dirname = os.path.dirname(args.mapping_file)
        tile_filepath = os.path.normpath(os.path.join(dirname, tile_filename))

        with open(tile_filepath) as file:
            tiles[gid] = m.loads(file.read())

print('{} 3D tileset{} found'.format(str(tilesets_3d_found).rjust(6), 's' if tilesets_3d_found > 1 else ''))
print('{} 3D tiles loaded'.format(str(len(tiles)).rjust(6)))

record_step_time()

print('Creating map...')
entities = []

worldspawn = m.Entity()
worldspawn.classname = 'worldspawn'
worldspawn.wad = tiles[2][0].wad
worldspawn.brushes = []

entities.append(worldspawn)

missing_gids = []

tiles_processed = 0
brush_count = 0

for layer in tilemap.layers:
    # Tile layer
    if isinstance(layer, tmx.Layer):
        for index, tile in enumerate(layer.tiles):
            # GIDs start at 1 so 0 is the empty 2D tile.
            if tile.gid == 0:
                continue

            # Warn if a tile is used in the 2D tilemap, but no mapping exists
            # for the 3D tiles.
            if not tiles.get(tile.gid) and tile.gid not in missing_gids:
                print("WARNING: Missing tile mapping for gid: {}".format(tile.gid))
                missing_gids.append(tile.gid)
                continue

            tiles_processed += 1

            x = index % width
            y = tilemap.height - (index // height)

            tilemap_offset_x = x * tile_size_3d + (tile_size_3d / 2) - (tilemap_width_3d / 2)
            tilemap_offset_y = y * tile_size_3d - (tile_size_3d / 2) - (tilemap_height_3d / 2)

            # Calculate tile transformation matrix
            mat = numpy.identity(4)
            mat[:3, 3] = tilemap_offset_x, tilemap_offset_y, 0

            flip_face = False

            if tile.hflip:
                mat = numpy.dot(mat, mathhelper.Matrices.horizontal_flip)
                flip_face = not flip_face

            if tile.dflip:
                mat = numpy.dot(mat, mathhelper.Matrices.diagonal_flip)
                flip_face = not flip_face

            if tile.vflip:
                mat = numpy.dot(mat, mathhelper.Matrices.vertical_flip)
                flip_face = not flip_face

            prefab = tiles[tile.gid]
            for entity in prefab:
                if entity.classname == 'worldspawn':
                    e = worldspawn

                else:
                    e = m.Entity()
                    e.classname = 'func_unknown'
                    e.brushes = []

                # Copy entity properties
                for key in entity.__dict__.keys():
                    if key != "brushes":
                        setattr(e, key, getattr(entity, key))

                # TODO: Transform white-listed properties
                # - origin
                # - angle

                # Transform brushes
                for copy_brush in entity.brushes:
                    brush_count += 1
                    b = m.Brush()
                    b.planes = []

                    for copy_plane in copy_brush.planes:
                        q = m.Plane()
                        q.points = []
                        q.texture_name = copy_plane.texture_name
                        q.offset = copy_plane.offset
                        q.rotation = copy_plane.rotation
                        q.scale = copy_plane.scale

                        for copy_point in copy_plane.points:
                            transformed_point = tuple(numpy.dot(mat, (*copy_point, 1))[:3])
                            q.points.append(transformed_point)

                        if flip_face:
                            # Re-order the points to flip the face
                            q.points = list(reversed(q.points))

                        b.planes.append(q)
                    e.brushes.append(b)

                if e.classname != 'worldspawn':
                    entities.append(e)

    # Object layer
    elif isinstance(layer, tmx.ObjectGroup):
        for obj in layer.objects:
            z = 0

            e = m.Entity()
            for prop in obj.properties:
                if prop.name == 'Z':
                    z = prop.value

                else:
                    setattr(e, prop.name, prop.value)

            scale = tile_size_3d / tile_size_2d
            ex = (obj.x * scale) - (tilemap_width_3d / 2)
            ey = (tilemap.height * tile_size_3d) - obj.y * scale - (tilemap_height_3d / 2)
            origin = ex, ey, z
            e.origin = "{} {} {}".format(*origin)
            e.classname = obj.name
            entities.append(e)


print('{} 2d tiles processed'.format(str(tiles_processed).rjust(6)))
record_step_time()

print('Saving: {}...'.format(os.path.basename(args.dest)))
with open(args.dest, 'w') as out_file:
    data = m.dumps(entities)
    out_file.write(data)

print('{} brushes written'.format(str(brush_count).rjust(6)))
record_step_time()

print('Complete!')
print('{:5.4f} total seconds elapsed'.format(sum(step_timing)))

sys.exit(0)
