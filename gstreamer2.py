# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
from functools import partial
import svgwrite
import numpy as np

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstBase', '1.0')
from gi.repository import GLib, GObject, Gst, GstBase
from PIL import Image

GObject.threads_init()
Gst.init(None)


def on_bus_message(bus, message, loop):
    t = message.type
    if t == Gst.MessageType.EOS:
        loop.quit()
    elif t == Gst.MessageType.WARNING:
        err, debug = message.parse_warning()
        sys.stderr.write('Warning: %s: %s\n' % (err, debug))
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        sys.stderr.write('Error: %s: %s\n' % (err, debug))
        loop.quit()
    return True


def on_new_sample(sink, appsrc, overlay, screen_size, appsink_size,
                  user_function):
    sample = sink.emit('pull-sample')
    buf = sample.get_buffer()
    result, mapinfo = buf.map(Gst.MapFlags.READ)
    if result:
        img = np.frombuffer(mapinfo.data, np.uint8)
        img = np.reshape(img, [appsink_size[1], appsink_size[0], -1])
        svg_canvas = svgwrite.Drawing('', size=(screen_size[0], screen_size[1]))
        appsrc_image = user_function(img, svg_canvas)

        if appsrc:
            data = appsrc_image.tobytes()
            appsrc_buffer = Gst.Buffer.new_allocate(None, len(data), None)
            appsrc_buffer.fill(0, data)
            appsrc.emit('push-buffer', appsrc_buffer)

        overlay.set_property('data', svg_canvas.tostring())
    buf.unmap(mapinfo)
    return Gst.FlowReturn.OK


def detectCoralDevBoard():
    try:
        if 'MX8MQ' in open('/sys/firmware/devicetree/base/model').read():
            print('Detected Edge TPU dev board.')
            return True
    except:
        pass
    return False


def run_pipeline(user_function,
                 src_size=(640, 480),
                 appsink_size=(320, 180),
                 use_appsrc=False):
    PIPELINE = 'rtspsrc location=rtsp://admin:1Bigred1@192.168.0.51:554//h264Preview_01_sub ! rtpjitterbuffer latency=300 ! rtph264depay ! h264parse ! omxh264dec ! {src_caps} ! {leaky_q} '
    if use_appsrc: APPSRC_PIPELINE = 'appsrc name=appsrc ! {appsrc_caps} '
    SRC_CAPS = 'video/x-raw,width={width},height={height}'
    if use_appsrc:
        PIPELINE += """ ! videoconvert ! videoscale ! {sink_caps} ! {leaky_q} ! {sink_element}
        """
        APPSRC_PIPELINE += """ ! {leaky_q} ! videoconvert
           ! rsvgoverlay name=overlay ! videoconvert ! nveglglessink window-x=100 window-y=500 window-width=640 window-height=480
        """
    else:
        PIPELINE += """ ! videoconvert ! videoscale ! {sink_caps} ! tee name=t
           t. ! {leaky_q} ! {sink_element}
           t. ! {leaky_q} ! videoconvert
              ! rsvgoverlay name=overlay ! videoconvert ! nveglglessink window-x=100 window-y=500 window-width=640 window-height=480
        """

    SINK_ELEMENT = 'appsink name=appsink sync=false emit-signals=true max-buffers=1 drop=true'
    DL_CAPS = 'video/x-raw,format=BGRA,width={width},height={height}'
    SINK_CAPS = 'video/x-raw,format=RGB,width={width},height={height}'
    APPSRC_CAPS = 'video/x-raw,format=RGB,width={width},height={height}'
    LEAKY_Q = 'queue max-size-buffers=1 leaky=downstream'
    
    src_caps = SRC_CAPS.format(width=src_size[0], height=src_size[1])
    dl_caps = DL_CAPS.format(width=appsink_size[0], height=appsink_size[1])
    sink_caps = SINK_CAPS.format(width=appsink_size[0], height=appsink_size[1])
    pipeline = PIPELINE.format(leaky_q=LEAKY_Q, src_caps=src_caps, dl_caps=dl_caps,
                               sink_caps=sink_caps, sink_element=SINK_ELEMENT)
    print('Gstreamer pipeline: ', pipeline)
    pipeline = Gst.parse_launch(pipeline)
    appsink = pipeline.get_by_name('appsink')

    if use_appsrc:
        appsrc_caps = APPSRC_CAPS.format(width=appsink_size[0], height=appsink_size[1])
        appsrc_pipeline = APPSRC_PIPELINE.format(leaky_q=LEAKY_Q,
                                                 appsrc_caps=appsrc_caps)
        print('Gstreamer appsrc pipeline: ', appsrc_pipeline)
        appsrc_pipeline = Gst.parse_launch(appsrc_pipeline)
        appsrc = appsrc_pipeline.get_by_name('appsrc')
        overlay = appsrc_pipeline.get_by_name('overlay')
    else:
        appsrc = None
        overlay = pipeline.get_by_name('overlay')

    appsink.connect('new-sample', partial(on_new_sample,
                                          appsrc=appsrc, overlay=overlay,
                                          screen_size=src_size, appsink_size=appsink_size,
                                          user_function=user_function))
    loop = GObject.MainLoop()

    # Set up a pipeline bus watch to catch errors.
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect('message', on_bus_message, loop)

    # Run pipeline.
    pipeline.set_state(Gst.State.PLAYING)
    if use_appsrc: appsrc_pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    except:
        pass

    # Clean up.
    pipeline.set_state(Gst.State.NULL)
    if use_appsrc: appsrc_pipeline.set_state(Gst.State.NULL)
    while GLib.MainContext.default().iteration(False):
        pass
