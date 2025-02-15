# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
from functools import partial
import re
import time

import numpy as np
from PIL import Image
import svgwrite
import gstreamer2

from pose_engine import PoseEngine

EDGES = (
    ('nose', 'left eye'),
    ('nose', 'right eye'),
    ('nose', 'left ear'),
    ('nose', 'right ear'),
    ('left ear', 'left eye'),
    ('right ear', 'right eye'),
    ('left eye', 'right eye'),
    ('left shoulder', 'right shoulder'),
    ('left shoulder', 'left elbow'),
    ('left shoulder', 'left hip'),
    ('right shoulder', 'right elbow'),
    ('right shoulder', 'right hip'),
    ('left elbow', 'left wrist'),
    ('right elbow', 'right wrist'),
    ('left hip', 'right hip'),
    ('left hip', 'left knee'),
    ('right hip', 'right knee'),
    ('left knee', 'left ankle'),
    ('right knee', 'right ankle'),
)

COLORS = {
    'nose': '#ff0055',
    'left eye': '#aa00ff',
    'right eye': '#9b00aa',
    'left ear': '#5500aa',
    'right ear': '#ff00ff',
    'left shoulder': '#aaff00',
    'right shoulder': '#ff5500',
    'left elbow': '#55ff00',
    'right elbow': '#ffaa00',
    'left wrist': '#00ff00',
    'right wrist': '#ffff00',
    'left hip': '#00aaff',
    'right hip': '#00ff55',
    'left knee': '#0055ff',
    'right knee': '#00ffaa',
    'left ankle': '#0000ff',
    'right ankle': '#00ffff',
}


def shadow_text(dwg, x, y, text, font_size=16):
    dwg.add(dwg.text(text, insert=(x + 1, y + 1), fill='black',
                     font_size=font_size, style='font-family:sans-serif'))
    dwg.add(dwg.text(text, insert=(x, y), fill='white',
                     font_size=font_size, style='font-family:sans-serif'))


def draw_pose(dwg, pose, x_scalar, y_scalar, point_scalar, threshold=0.2):
    xys = {}
    for label, keypoint in pose.keypoints.items():
        if keypoint.score < threshold: continue
        xys[label] = (int(keypoint.yx[1] * x_scalar), int(keypoint.yx[0] * y_scalar))
        dwg.add(dwg.circle(center=(int(keypoint.yx[1] * x_scalar), int(keypoint.yx[0] * y_scalar)), r=4 * point_scalar,
                           fill=COLORS[label], fill_opacity=keypoint.score, stroke=COLORS[label]))

    for a, b in EDGES:
        if a not in xys or b not in xys: continue
        ax, ay = xys[a]
        bx, by = xys[b]
        dwg.add(dwg.line(start=(ax, ay), end=(bx, by), stroke=COLORS[a], stroke_width=4 * point_scalar, stroke_opacity=0.2))


def run(callback):
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--model', help='.tflite model path.', required=False)
    parser.add_argument('--res', help='Resolution', default='640x480',
                        choices=['480x360', '640x480', '1280x720'])
    parser.add_argument('--camera', help='Camera', default='ip',
                        choices=['ip', 'built-in', 'realsense'])
    args = parser.parse_args()

    default_model = 'models/posenet_mobilenet_v1_075_%d_%d_quant_decoder_edgetpu.tflite'
    if args.res == '480x360':
        appsink_size = (480, 360)
        model = args.model or default_model % (353, 481)
    elif args.res == '640x480':
        appsink_size = (640, 480)
        model = args.model or default_model % (481, 641)
    elif args.res == '1280x720':
        appsink_size = (1280, 720)
        model = args.model or default_model % (721, 1281)
    camera = args.camera

    if camera == 'ip':
        src_size = (640, 480)
    elif camera == 'built-in':
        src_size = (1280, 720)
    elif camera == 'realsense':
        src_size = (1920, 1080)

    print('Loading model: ', model)
    engine = PoseEngine(model, mirror=False)

    x_scalar = src_size[0] / appsink_size[0]
    y_scalar = src_size[1] / appsink_size[1]
    point_scalar = src_size[0] / 480;

    gstreamer2.run_pipeline(partial(callback, engine, x_scalar, y_scalar, point_scalar),
                           src_size, appsink_size, camera)


def main():
    last_time = time.monotonic()
    n = 0
    sum_fps = 0
    sum_process_time = 0
    sum_inference_time = 0

    def render_overlay(engine, x_scalar, y_scalar, point_scalar, image, svg_canvas):
        nonlocal n, sum_fps, sum_process_time, sum_inference_time, last_time
        start_time = time.monotonic()
        outputs, inference_time = engine.DetectPosesInImage(image)
        end_time = time.monotonic()
        n += 1
        sum_fps += 1.0 / (end_time - last_time)
        sum_process_time += 1000 * (end_time - start_time) - inference_time
        sum_inference_time += inference_time
        last_time = end_time
        text_line = 'PoseNet: %.1fms Frame IO: %.2fms TrueFPS: %.2f Nposes %d' % (
            sum_inference_time / n, sum_process_time / n, sum_fps / n, len(outputs)
        )
        # print(text_line)

        shadow_text(svg_canvas, 10, 20, text_line)
        for pose in outputs:
            draw_pose(svg_canvas, pose, x_scalar, y_scalar, point_scalar)

    run(render_overlay)


if __name__ == '__main__':
    main()
