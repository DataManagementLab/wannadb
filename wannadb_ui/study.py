import logging
import os
import time
from functools import wraps

from PyQt6.QtCore import QObject, QTimer, QDateTime, pyqtSignal
from typing import Dict, Callable

logger: logging.Logger = logging.getLogger(__name__)


class Tracker(QObject):
    _instance = None  # Class-level attribute to store the singleton instance
    time_spent_signal = pyqtSignal(str, float)  # Define the signal with window name and time spent

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Tracker, cls).__new__(cls, *args, **kwargs)
            cls._instance._initialized = False

        return cls._instance

    def __init__(self):
        if not self._initialized:
            super().__init__()  # Call the QObject initializer
            self.window_open_time = None
            self.timer = QTimer()
            self.timer.timeout.connect(self.calculate_time_spent)
            self.button_click_counts: Dict[str, int] = {}
            self.total_window_open_time = {}
            self._initialized = True
            self.log = ''

    def dump_report(self):
        tick: float = time.time()
        logger.info(f"Writing the reports in the log file")
        log_directory = './logs'
        log_file = os.path.join(log_directory, 'user_report.txt')
        os.makedirs(log_directory, exist_ok=True)
        with open(log_file, 'w') as file:
            file.write(self.log)
            file.write("\nTotal Statistics:\n")
            file.write(f"\nButton information:\n")
            for button_name, number_of_clicks in self.button_click_counts.items():
                file.write(f"\t'{button_name}' button has been clicked {number_of_clicks} times\n")
            file.write(f"Window Information:\n")
            for window_name, time_open_in_sec in self.total_window_open_time.items():
                file.write(f"\t{window_name} was open for a total of {time_open_in_sec} seconds\n")
        tack: float = time.time()
        logger.info(f"Writing the report in {round(tick - tack, 2)} seconds")

    def start_timer(self, window_name: str):
        self.window_open_time = QDateTime.currentDateTime()
        self.timer.start(1000)
        self.log += f"{window_name} was opened"

    def stop_timer(self, window_name: str):
        self.timer.stop()
        logger.debug(f"window_name = {window_name}")
        self.calculate_time_spent(window_name)

    def calculate_time_spent(self, window_name: str):
        if self.window_open_time:
            current_time = QDateTime.currentDateTime()
            time_spent = self.window_open_time.msecsTo(current_time) / 1000.0  # Convert to seconds
            self.time_spent_signal.emit(window_name, time_spent)
            self.window_open_time = None
            if window_name in self.total_window_open_time:
                self.total_window_open_time[window_name] += time_spent
            else:
                self.total_window_open_time[window_name] = time_spent
            self.log += f'Time spent in {window_name} : {round(time_spent, 2)} seconds.\n'

    def track_button_click(self, button_name: str):
        if button_name in self.button_click_counts:
            self.button_click_counts[button_name] += 1
        else:
            self.button_click_counts[button_name] = 1
        self.log += f'{button_name} was clicked.\n'

    def get_button_click_count(self, button_name: str) -> int:
        return self.button_click_counts.get(button_name, 0)


def track_button_click(button_name: str):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            print(f"Arguments passed to {func.__name__}: args={args}, kwargs={kwargs}")
            args = tuple()  # empty args, because .connect() implicit arguments are added, which result in an erroneous call of the decorated method
            Tracker().track_button_click(button_name)
            return func(self, *args, **kwargs)

        return wrapper

    return decorator
