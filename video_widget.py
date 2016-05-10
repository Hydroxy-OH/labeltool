import os
import time
import threading
from enum import Enum

import cv2
import dlib
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from image_label import ImageLabel


class VideoStatus(Enum):
    not_loaded = -1
    pause = 0
    play_forward = 1
    play_backward = 2
    frame_forward = 3
    frame_backward = 4


class Video(QObject):

    signal_frame_updated = pyqtSignal(QPixmap, name='frameUpdated')
    signal_tracking_updated = pyqtSignal(list)

    def __init__(self, filepath=None, max_buf_size=500, max_fps=50.0):
        super(Video, self).__init__()
        self.cap = cv2.VideoCapture()
        self.trackers = []
        self.filepath = filepath
        self.frame_buf = {}
        self.frame_buf_order = []
        self.max_buf_size = max_buf_size
        self.max_fps = max_fps
        self.frame_cursor = -1
        self.status = VideoStatus.not_loaded
        if filepath is not None:
            self.load(filepath)

    def load(self, filepath):
        self.cap = cv2.VideoCapture(filepath)
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = int(round(self.cap.get(cv2.CAP_PROP_FPS)))
        self.frame_num = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.status = VideoStatus.pause

    def mat2qpixmap(self, img):
        tmp_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        height, width, depth = tmp_img.shape
        bytes_per_line = depth * width
        qt_img = QImage(tmp_img.data, width, height, bytes_per_line,
                        QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_img)
        return pixmap

    def add2buf(self, cursor, img):
        if cursor in self.frame_buf:
            return
        if len(self.frame_buf) >= self.max_buf_size:
            earlist = self.frame_buf_order[0]
            del self.frame_buf[earlist]
            del self.frame_buf_order[0]
        self.frame_buf[cursor] = img
        self.frame_buf_order.append(cursor)

    def frame_forward(self):
        if self.frame_cursor < self.frame_num - 1:
            self.frame_cursor += 1
            if self.status != VideoStatus.play_forward:
                self.status = VideoStatus.frame_forward
        if self.frame_cursor in self.frame_buf:
            img = self.frame_buf[self.frame_cursor]
        else:
            ret, img = self.cap.read()
            if ret == 0:
                return
            else:
                self.add2buf(self.frame_cursor, img)
        self.track(img)
        self.signal_frame_updated.emit(self.mat2qpixmap(img))

    def frame_backward(self):
        if self.frame_cursor > 0:
            self.frame_cursor -= 1
            if self.status != VideoStatus.play_backward:
                self.status = VideoStatus.frame_backward
        if self.frame_cursor in self.frame_buf:
            img = self.frame_buf[self.frame_cursor]
        else:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.frame_cursor)
            ret, img = self.cap.read()
            if ret == 0:
                return
            else:
                self.add2buf(self.frame_cursor, img)
        self.track(img)
        self.signal_frame_updated.emit(self.mat2qpixmap(img))

    def jump_to_frame(self, cursor):
        self.status = VideoStatus.pause
        self.frame_cursor = cursor
        if self.frame_cursor in self.frame_buf:
            img = self.frame_buf[self.frame_cursor]
        else:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.frame_cursor)
            ret, img = self.cap.read()
            if ret == 0:
                return
            else:
                self.add2buf(self.frame_cursor, img)
        self.signal_frame_updated.emit(self.mat2qpixmap(img))

    def play_forward(self):
        min_interval = 1 / self.max_fps
        while (self.status == VideoStatus.play_forward and
               self.frame_cursor < self.frame_num - 1):
            start = time.time()
            self.frame_forward()
            ellapsed = time.time() - start
            if ellapsed < min_interval:
                time.sleep(min_interval - ellapsed)

    def play_backward(self):
        min_interval = 1 / self.max_fps
        while (self.status == VideoStatus.play_backward and
               self.frame_cursor > 0):
            start = time.time()
            self.frame_backward()
            ellapsed = time.time() - start
            if ellapsed < min_interval:
                time.sleep(min_interval - ellapsed)

    def play_ctrl(self, status):
        self.status = status
        if self.status == VideoStatus.play_forward:
            t = threading.Thread(target=self.play_forward)
            t.daemon = True
            t.start()
        elif self.status == VideoStatus.play_backward:
            t = threading.Thread(target=self.play_backward)
            t.daemon = True
            t.start()
        elif self.status == VideoStatus.frame_forward:
            self.frame_forward()
        elif self.status == VideoStatus.frame_backward:
            self.frame_backward()

    def track(self, img):
        rects = []
        for tracker in self.trackers:
            tracker.update(img)
            rect = tracker.get_position()
            l = max(int(rect.left()), 0)
            t = max(int(rect.top()), 0)
            r = min(int(rect.right()), self.frame_width)
            b = min(int(rect.bottom()), self.frame_height)
            rects.append(QRect(l, t, r - l, b - t))
        self.signal_tracking_updated.emit(rects)

    @pyqtSlot(list)
    def set_trackers(self, rects):
        self.trackers = []
        for rect in rects:
            tracker = dlib.correlation_tracker()
            tracker.start_track(
                self.frame_buf[self.frame_cursor],
                dlib.rectangle(rect.left(), rect.top(),
                               rect.right(), rect.bottom())
            )
            self.trackers.append(tracker)


class VideoWidget(QWidget):
    signal_play_ctrl = pyqtSignal(VideoStatus)
    signal_video_loaded = pyqtSignal(str)
    signal_frame_updated = pyqtSignal(int)

    def __init__(self, parent=None, with_filename=True, with_slider=True,
                 max_buf_size=500, max_fps=50.0):
        super(VideoWidget, self).__init__(parent)
        self.with_filename = with_filename
        self.with_slider = with_slider
        self.video = Video(max_buf_size=max_buf_size, max_fps=max_fps)
        self.init_ui()
        self.installEventFilter(self)
        if self.with_slider:
            self.slider.sliderReleased.connect(self.on_slider_released)
        self.video.signal_tracking_updated.connect(self.label_frame.update_rects)
        self.label_frame.signal_rect_changed.connect(self.video.set_trackers)

    def init_ui(self):
        self.grid_layout = QGridLayout()
        if self.with_filename:
            stretch = [1, 10]
        else:
            stretch = [10]
        if self.with_slider:
            stretch.append(1)
        for i in range(len(stretch)):
            self.grid_layout.setRowStretch(i, stretch[i])
        if self.with_filename:
            self.set_label_filename(0)
            self.set_label_frame(1)
        else:
            self.set_label_frame(0)
        if self.with_slider:
            self.set_slider(len(stretch) - 1)
        self.setLayout(self.grid_layout)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_label_filename(self, row_pos):
        self.label_filename = QLabel('filename')
        self.label_filename.setAlignment(Qt.AlignCenter)
        self.grid_layout.addWidget(self.label_filename, row_pos, 0)

    def set_label_frame(self, row_pos):
        self.label_frame = ImageLabel('video')
        self.label_frame.setAlignment(Qt.AlignCenter)
        self.label_frame.setStyleSheet('border: 1px solid black')
        self.grid_layout.addWidget(self.label_frame, row_pos, 0)

    def set_slider(self, row_pos):
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setTickInterval(1)
        self.slider.setValue(0)
        self.slider.setEnabled(False)
        self.grid_layout.addWidget(self.slider, row_pos, 0)

    def eventFilter(self, object, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_D:
                self.video.play_ctrl(VideoStatus.frame_forward)
                return True
            elif key == Qt.Key_A:
                self.video.play_ctrl(VideoStatus.frame_backward)
                return True
            elif key == Qt.Key_Left:
                if self.video.status == VideoStatus.play_backward:
                    self.video.play_ctrl(VideoStatus.pause)
                elif self.video.status != VideoStatus.not_loaded:
                    self.video.play_ctrl(VideoStatus.play_backward)
                return True
            elif key == Qt.Key_Right:
                if self.video.status == VideoStatus.play_forward:
                    self.video.play_ctrl(VideoStatus.pause)
                elif self.video.status != VideoStatus.not_loaded:
                    self.video.play_ctrl(VideoStatus.play_forward)
                return True
            elif key == Qt.Key_Space:
                self.video.play_ctrl(VideoStatus.pause)
                return True
            elif key == Qt.Key_Alt:
                self.label_frame.show_reticle = not self.label_frame.show_reticle
                self.label_frame.update()
        return False

    @pyqtSlot()
    def open_file(self):
        self.filename, _ = QFileDialog.getOpenFileName(
            self, 'Load video', './', 'Videos (*.mp4 *.avi *.mkv *.flv *.m4v)')
        if not self.filename:
            return
        if self.with_filename:
            self.label_filename.setText(os.path.basename(self.filename))
        if self.with_slider:
            self.slider.setEnabled(True)
        self.video.load(self.filename)
        self.video.signal_frame_updated.connect(self.update_frame)
        self.video.frame_forward()
        self.signal_video_loaded.emit(self.filename)

    @pyqtSlot(QPixmap)
    def update_frame(self, pixmap):
        frame_cursor = self.video.frame_cursor
        frame_num = self.video.frame_num
        self.label_frame.show_img(pixmap)
        self.signal_frame_updated.emit(frame_cursor)
        if self.with_slider:
            self.slider.setValue(
                int(frame_cursor * self.slider.maximum() / frame_num))

    @pyqtSlot()
    def on_slider_released(self):
        progress = self.slider.value() / self.slider.maximum()
        cursor = int(self.video.frame_num * progress)
        self.video.jump_to_frame(cursor)

    @pyqtSlot(int)
    def jump_to_frame(self, cursor):
        self.video.jump_to_frame(cursor)