# People and Gender Counter (CCTV)
# Ammar Chalifah (July 2020)
#
# Created as an educative project
# at Bisa AI x Institut Teknologi Bandung (Indonesia)

# Libraries
import numpy as np
import cv2
print('[INFO] cv2 imported. cv2 version: {}'.format(cv2.__version__))
import pandas as pd
import dlib
print('[INFO] dlib imported. dlib version: {}'.format(dlib.__version__))
import imutils
print('[INFO] imutils imported. imutils version: {}'.format(imutils.__version__))

from matplotlib import pyplot as plt
import csv
import time
import argparse
import math
import os
import datetime
print('[INFO] supporting libraries imported.')

from functions.centroidtracker import CentroidTracker
print('[INFO] functions/centroidtracker imported')
from functions.trackableobject import TrackableObject, GenderObject
print('[INFO] functions/trackableobject imported')

from functions import config_util
print('[INFO] config util loaded')

from functions import label_map_util
print('[INFO] label map util imported')

from object_detection.builders import model_builder
print('[INFO] model builder loaded')

print('[INFO] importing tensorflow...')
import tensorflow as tf
from tensorflow.keras.models import load_model
print('[INFO] tensorflow imported. tensorflow version: {}'.format(tf.__version__))

tf.get_logger().setLevel('ERROR')

# Parser
# Specify all the parameters needed by the end user in order to get desirable outcome.

parser = argparse.ArgumentParser()

parser.add_argument('-m', '--model', default = 'efficientdet', help = 'Model name to be used. Choose between [ssd inception, ssd mobilenet, faster rcnn resnet]')
parser.add_argument('-i', '--input_path', default = 'videos/WalkByShop1cor.mpg', help ='path of file')
parser.add_argument('-f', '--skip_frame', default = 20, help='number of frames skipped for each detection')
parser.add_argument('-c', '--classes_to_detect', default = ['person'], help = 'classes name to detect')
parser.add_argument('-d', '--distance_threshold', default = 70, help = 'maximum distance of object displacement to be considered as one object')
parser.add_argument('-l', '--longest_disappear', default = 15, help = 'maximum number of frames the object disappeared')
parser.add_argument('-g', '--log', default = True, help = 'Save the log?')
parser.add_argument('-o', '--output', default = 'videos/output.avi', help ='path to written video file')

args = parser.parse_args()

# -----------
# HELPER CODE
# -----------
def load_image_into_numpy_array(image):
    """Function to convert image into numpy array"""
    (im_width, im_height) = image.size
    return np.array(image.getdata()).reshape(
        (im_height, im_width, 3)).astype(np.uint8)

def clean_detection_result(boxes, classes, scores, classes_to_detect, threshold = 0.5):
    """
    Function to remove all prediction results that are not included in classes_to_detect.
    In default, this function will remove all predictions other than 'person' type.

    Args:
        boxes, classes, scores -> detection from TF2 Object Detection Model.
        classes_to_detect -> list of strings. default: ['person']
        threshold -> minimum score
    Returns:
        new_boxes, new_classes, new_scores -> numpy array of cleaned prediction result.
    """
    new_boxes = []
    new_classes = []
    new_scores = []
    for i in range(scores.shape[0]):
        if scores[i]>threshold and category_index[classes[i]]['name'] in classes_to_detect:
            new_boxes.append(boxes[i])
            new_classes.append(classes[i])
            new_scores.append(scores[i])
    return np.asarray(new_boxes), np.asarray(new_classes), np.asarray(new_scores)

#------------VIDEO STREAM--------------
# Define the video stream
print('[INFO] creating video capture ...')
if args.input_path == '0' or args.input_path == 'webcam':
    cap = cv2.VideoCapture(0) 
else:
    cap = cv2.VideoCapture(args.input_path)  # Change only if you have more than one webcams 

fps = cap.get(cv2.CAP_PROP_FPS)

#Target size of the video stream
font = cv2.FONT_HERSHEY_SIMPLEX

writer = None
W = None
H = None

# Model choosing
# -----------DETECTION MODEL-----------------
# Note for user:
# Please modify this variable if you use another model.
# Make sure to download the model from TensorFlow 2 Object Detection Model Zoo.
modelname = {
    'ssd mobilenet':'ssd_mobilenet_v2_fpnlite_320x320_coco17_tpu-8',
    'centernet':'centernet_hg104_1024x1024_kpts_coco17_tpu-32',
    'faster rcnn inception': 'faster_rcnn_inception_resnet_v2_1024x1024_coco17_tpu-8',
    'faster rcnn resnet101': 'faster_rcnn_resnet101_v1_1024x1024_coco17_tpu-8',
    'ssd resnet fpn': 'ssd_resnet50_v1_fpn_640x640_coco17_tpu-8',
    'efficientdet':'efficientdet_d0_coco17_tpu-32'
}

MODEL_NAME = modelname[args.model]
# Path to frozen detection graph. This is the actual model that is used for the object detection.
PATH_TO_CKPT = os.path.join('models', os.path.join(MODEL_NAME, 'checkpoint/'))
# List of the strings that is used to add correct label for each box.
PATH_TO_CFG = os.path.join('models', os.path.join(MODEL_NAME, 'pipeline.config'))
PATH_TO_LABELS = os.path.join('label', 'mscoco_label_map.pbtxt')
# Number of classes to detect
NUM_CLASSES = 90

#----------------HUMAN COUNTER-----------------
humancounter = 0
first_detection = True

# Loading label map
# Label maps map indices to category names, so that when our convolution network predicts `5`, we know that this corresponds to `airplane`.  Here we use internal utility functions, but anything that returns a dictionary mapping integers to appropriate string labels would be fine
category_index = label_map_util.create_category_index_from_labelmap(PATH_TO_LABELS, use_display_name=True)

#Object Tracking Helper Code
ct = CentroidTracker(maxDisappeared=args.longest_disappear, maxDistance=args.distance_threshold)
trackers = []
trackableObjects = {}
genderObjects = {}

framecount = 0
totalDown = 0
totalUp = 0

womanUp = 0
womanDown = 0
manUp = 0
manDown = 0

# Model Loading
print('[INFO] loading detection model ...')
configs = config_util.get_configs_from_pipeline_file(PATH_TO_CFG)
model_config = configs['model']
detection_model = model_builder.build(model_config=model_config, is_training = False)

ckpt = tf.compat.v2.train.Checkpoint(model = detection_model)
ckpt.restore(os.path.join(PATH_TO_CKPT, 'ckpt-0')).expect_partial()
print('[INFO] detection model loaded')

# Logger
if args.log:
    log_fields = ['timestamp', 'video time', 'track information', 'total up', 'man up', 'woman up', 'total down', 'man down', 'woman down']
    with open('log.csv', 'w') as f:
        log_writer = csv.writer(f)
        log_writer.writerow(log_fields)

# Gender Model Loading
# Feel free to use any gender classification model in h5 format
# The output of the prediction an array with length 2, each of them represents the confidence of
# 'woman' and 'man' class
print('[INFO] loading gender classifier model...')
gender_model = load_model('models/model.h5')
g_classes = ['woman', 'man']
print('[INFO] gender classifier model loaded')

@tf.function
def detect_fn(image):
    """Detect objects in image."""

    image, shapes = detection_model.preprocess(image)
    prediction_dict = detection_model.predict(image, shapes)
    detections = detection_model.postprocess(prediction_dict, shapes)

    return detections, prediction_dict, tf.reshape(shapes, [-1])

# Detection
while True:
    #Initialize start time to count time elapsed for each frame.
    start_time = time.time()

    # Read frame from camera
    ret, image_np = cap.read()

    image_np = imutils.resize(image_np, width = 800)

    if W is None or H is None:
        (H, W) = image_np.shape[:2]

    rgb = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)

    if args.output is not None and writer is None:
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(args.output, fourcc, 30, (W, H), True)

    status = 'waiting'
    rects = []
    centroCoordDict = {}

    # Expand dimensions since the model expects images to have shape: [1, None, None, 3]
    image_np_expanded = np.expand_dims(image_np, axis=0)

    if framecount % int(args.skip_frame) == 0:
        status = 'detecting'
        trackers = []

        input_tensor = tf.convert_to_tensor(np.expand_dims(image_np, 0), dtype=tf.float32)
        detections, predictions_dict, shapes = detect_fn(input_tensor)

        label_id_offset = 1

        boxes = detections['detection_boxes'][0].numpy()
        classes = (detections['detection_classes'][0].numpy() + label_id_offset).astype(int)
        scores = detections['detection_scores'][0].numpy()

        # Remove all results that are not a member of [classes_to_detect] and has score lower than 50%
        boxes, classes, scores = clean_detection_result(boxes, classes, scores, args.classes_to_detect, threshold = 0.5)

        # Bounding boxes
        for box in boxes:
            box = box*np.array([H, W, H, W])
            ymin, xmin, ymax, xmax = box.astype('int')

            cX = int((xmin + xmax) / 2.0)
            cY = int((ymin + ymax) / 2.0)
            
            tracker = dlib.correlation_tracker()
            rect = dlib.rectangle(xmin, ymin, xmax, ymax)
            tracker.start_track(rgb, rect)

            trackers.append(tracker)

            g_image = image_np[ymin:ymax, xmin:xmax]
            g_image = cv2.cvtColor(g_image, cv2.COLOR_BGR2GRAY)
            g_image = g_image.astype('float')/255.0
            g_image = np.expand_dims(g_image, axis = 0)
            g_image = np.expand_dims(g_image, axis =-1)

            if g_image is None:
                gender = 'undetected'
            else:
                confidence = gender_model.predict(g_image)[0]
                g_idx = np.argmax(confidence)
                gender = g_classes[g_idx]

            centroCoordDict[(cX, cY)] = (xmin, ymin, xmax, ymax, gender)
    else:
        for tracker in trackers:
            status = 'tracking'

            tracker.update(rgb)
            pos = tracker.get_position()

            xmin = int(pos.left())
            ymin = int(pos.top())
            xmax = int(pos.right())
            ymax = int(pos.bottom())

            g_image = image_np[ymin:ymax, xmin:xmax]
            g_image = cv2.cvtColor(g_image, cv2.COLOR_BGR2GRAY)
            g_image = g_image.astype('float')/255.0
            g_image = np.expand_dims(g_image, axis = 0)
            g_image = np.expand_dims(g_image, axis =-1)

            if g_image is None:
                gender = 'undetected'
            else:
                confidence = gender_model.predict(g_image)[0]
                g_idx = np.argmax(confidence)
                gender = g_classes[g_idx]

            cX = int((xmin + xmax) / 2.0)
            cY = int((ymin + ymax) / 2.0)
            centroCoordDict[(cX, cY)] = (xmin, ymin, xmax, ymax, gender)

            rects.append((xmin, ymin, xmax, ymax))
    
    # use the centroid tracker to associate the old object centroids
    # with the newly computer object centroids
    objects = ct.update(rects)

    # CSV Logger
    log_track = []

    for (objectID, centroid) in objects.items():
        
        # check to see if a trackable object exists for the current object ID
        go = genderObjects.get(objectID, None)
        to = trackableObjects.get(objectID, None)

        if go is None:
            # masukkan fungsi prediksi gender di sini
            # dengan masukan frame dan bounding box
            # yang bisa diakses dari dict centroid -> koordinat
            if centroCoordDict[(centroid[0], centroid[1])][4] is not 'undetected':
                go = GenderObject(objectID, centroCoordDict[(centroid[0], centroid[1])][4])
                go.determine_gender()
        elif len(go.genders) < 3:
            # masukkan fungsi prediksi gender di sini
            # dengan masukan frame dan bounding box
            # yang bisa diakses dari dict centroid -> koordinat
            if centroCoordDict[(centroid[0], centroid[1])][4] is not 'undetected':
                go.genders.append(centroCoordDict[(centroid[0], centroid[1])][4])
                go.determine_gender()

        genderObjects[objectID] = go

        if to is None:
            to = TrackableObject(objectID, centroid)
        else:
            y = [c[1] for c in to.centroids]
            direction = centroid[1] - y[0]
            to.centroids.append(centroid)

            if not to.counted:
                if direction < -(H/5):
                    totalUp += 1
                    if go.gender == 'man':
                        manUp += 1
                    else:
                        womanUp += 1
                    to.counted = True
                elif direction > H/5:
                    totalDown += 1
                    if go.gender == 'man':
                        manDown += 1
                    else:
                        womanDown += 1
                    to.counted = True
        
        trackableObjects[objectID] = to

        log_track.append({'ID':objectID, 'location': centroid, 'gender': go.gender})

        #CREATE TUPLE FOR LOG with format (ID, centroid, height, gender)

        #Centroid display
        text = "ID {}".format(objectID)
        image_np = cv2.putText(image_np, text, (centroid[0] - 10, centroid[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        image_np = cv2.circle(image_np, (centroid[0], centroid[1]), 4, (0, 255, 0), -1)

    #Counter display
    info = [
        ("Up", totalUp),
        ("Down", totalDown),
        ("Status", status),
    ]

    infoGender = [
        (manUp, womanUp),
        (manDown, womanDown)
    ]

    for (i, (k, v)) in enumerate(info):
        if i < 2:
            text = "{}: {} (Female: {} Male: {})".format(k, v, infoGender[i][1], infoGender[i][0])
        else:
            text = "{}: {}".format(k, v)
        image_np = cv2.putText(image_np, text, (10, H - ((i * 20) + 20)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 255), 1)
    
    if writer is not None:
        writer.write(image_np)
    
    # Timestamp
    timeDiff = time.time() - start_time
    print('------ {:f} seconds ------'.format(timeDiff))
    if (timeDiff < 1.0/(fps)): time.sleep(1.0/(fps) - timeDiff)

    # Logger 
    if args.log:
        log_time = datetime.datetime.now().strftime("%H:%M:%S")
        log_vidtime = datetime.timedelta(seconds = framecount/fps)

        log_fields = [log_time, log_vidtime, log_track, totalUp, manUp, womanUp, totalDown, manDown, womanDown]

        with open('log.csv', 'a') as f:
            log_writer = csv.writer(f)
            log_writer.writerow(log_fields)

    # Display output
    cv2.imshow('object detection', image_np)
    # Frame count update
    framecount += 1

    if cv2.waitKey(25) & 0xFF == ord('q'):
        cv2.destroyAllWindows()
        break

if writer is not None:
    writer.release()

if args.input_path == '0' or args.input_path == 'webcam':
    cap.stop() 
else:
    cap.release()