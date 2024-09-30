import json
import logging
import os
import time
from collections import defaultdict
from functools import wraps

from PyQt6.QtCore import QObject, QTimer, QDateTime, pyqtSignal
from typing import Dict, Callable

logger: logging.Logger = logging.getLogger(__name__)


# Singleton class for tracking user interaction with a GUI
class Tracker(QObject):
    _instance = None  # Class-level attribute to store the singleton instance
    time_spent_signal = pyqtSignal(str, float)  # Define the signal with window name and time spent

    def __new__(cls, *args, **kwargs):
        """Singleton pattern ensures one instance of the class"""
        if not cls._instance:
            cls._instance = super(Tracker, cls).__new__(cls, *args, **kwargs)
            cls._instance._initialized = False

        return cls._instance

    def __init__(self):
        """Initialize tracking properties if not already initialized"""
        if not self._initialized:
            super().__init__()  # Call the QObject initializer
            self.window_open_times = {}
            self.timer = QTimer()
            self.button_click_counts = defaultdict(int)
            self.tooltips_hovered_counts = defaultdict(int)
            self.total_window_open_times = {}
            self._initialized = True
            self.log = ''
            self.sequence_number = 1
            self.json_data = []

    def dump_report(self):
        """Dumps the interaction data to two report files.
        One of them contains a json representations of the user activiy, the other
        contains natural text."""
        log_directory = './logs'
        log_file = os.path.join(log_directory, 'user_report.txt')
        os.makedirs(log_directory, exist_ok=True)

        tick: float = time.time()
        with open(log_file, 'w') as file:
            file.write(self.log)
            file.write("\nTotal Statistics:\n")
            file.write(f"\nButton information:\n")
            for button_name, number_of_clicks in self.button_click_counts.items():
                file.write(f"\t'{button_name}' button has been clicked {number_of_clicks} times\n")
            file.write(f"Window Information:\n")
            for window_name, time_open_in_sec in self.total_window_open_times.items():
                file.write(f"\t{window_name} was open for a total of {time_open_in_sec} seconds\n")
        tack: float = time.time()
        logger.info(f"Wrote the report in {round(tick - tack, 2)} seconds")

        tick = time.time()
        json_string = json.dumps(self.json_data, indent=4)
        with open(os.path.join(log_directory, 'json_report.txt'), 'w') as file:
            file.write(json_string)
        tack = time.time()
        logger.info(f"Dumped the json report file in {round(tick - tack, 2)} seconds")

    def start_timer(self, window_name: str):
        """Starts the timer for tracking window open time"""
        self.window_open_times[window_name] = QDateTime.currentDateTime()
        self.timer.start(1000)
        self.log += f"{self.sequence_number}. {window_name} was opened\n"
        self.json_data.append({'type': 'window', 'action': 'open', 'identifier': window_name})
        self.sequence_number += 1

    def stop_timer(self, window_name: str):
        """Stops the timer for a window and calculates the time spent"""
        self.timer.stop()
        logger.debug(f"window_name = {window_name}")
        self.calculate_time_spent(window_name)

    def calculate_time_spent(self, window_name: str):
        """Calculates the time spent in a window and logs the result"""
        if self.window_open_times[window_name]:
            current_time = QDateTime.currentDateTime()
            time_spent = self.window_open_times[window_name].msecsTo(current_time) / 1000.0  # Convert to seconds
            self.time_spent_signal.emit(window_name, time_spent)
            self.window_open_times[window_name] = None
            if window_name in self.total_window_open_times:
                self.total_window_open_times[window_name] += time_spent
            else:
                self.total_window_open_times[window_name] = time_spent
            self.log += f'{self.sequence_number}. {window_name} was closed. Time spent in {window_name} : {round(time_spent, 2)} seconds.\n'
            self.sequence_number += 1
            self.json_data.append(
                {'type': 'window', 'action': 'close', 'identifier': window_name, 'time_open': time_spent})

    def track_button_click(self, button_name: str):
        """Tracks button clicks and logs them. Helper method for the decorator below"""
        self.button_click_counts[button_name] += 1
        self.log += f'{self.sequence_number}. {button_name} was clicked.\n'
        self.sequence_number += 1
        self.json_data.append({'type': 'button', 'identifier': button_name})

    def track_tooltip_activation(self, tooltip_object: str):
        """Tracks tooltip activations and logs them. Must be manually wired to every added tooltip"""
        self.tooltips_hovered_counts[tooltip_object] += 1
        self.log += f'{self.sequence_number}. The following tooltip was activated:\n {tooltip_object} \n'
        self.sequence_number += 1
        self.json_data.append({'type': 'tooltip', 'identifier': tooltip_object})


def track_button_click(button_name: str):
    """Decorator to track button clicks. Add to function signature behind a button to start logging"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            print(f"Arguments passed to {func.__name__}: args={args}, kwargs={kwargs}")
            args = tuple()  # empty args, because .connect() implicit arguments are added, which result in an erroneous call of the decorated method
            Tracker().track_button_click(button_name)
            return func(self, *args, **kwargs)

        return wrapper

    return decorator
