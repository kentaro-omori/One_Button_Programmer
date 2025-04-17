#!/usr/bin/env python3
"""
main.py: Raspberry Pi Zero 2 W で ATtiny1616 に UPDI 経由で書き込むプログラム
"""

import os
import time
import subprocess
import glob
import RPi.GPIO as GPIO


class LED:
    """GPIO ピン制御用の LED クラス"""

    def __init__(self, pin):
        """
        Args:
            pin (int): BCM モードの GPIO ピン番号
        """
        self.pin = pin
        GPIO.setup(self.pin, GPIO.OUT)
        GPIO.output(self.pin, GPIO.LOW)

    def on(self):
        """LED を点灯する"""
        GPIO.output(self.pin, GPIO.HIGH)

    def off(self):
        """LED を消灯する"""
        GPIO.output(self.pin, GPIO.LOW)


class Buzzer:
    """GPIO ピン制御用のブザー クラス"""

    def __init__(self, pin):
        """
        Args:
            pin (int): BCM モードの GPIO ピン番号
        """
        self.pin = pin
        GPIO.setup(self.pin, GPIO.OUT)
        GPIO.output(self.pin, GPIO.LOW)

    def buzz(self, duration_sec):
        """
        Args:
            duration_sec (float): 鳴動時間（秒）
        """
        # 440Hz の PWM でブザーを鳴動
        pwm = GPIO.PWM(self.pin, 440)
        pwm.start(50)  # デューティ比 50%
        time.sleep(duration_sec)
        pwm.stop()
        GPIO.output(self.pin, GPIO.LOW)


class Button:
    """GPIO ピン入力用のボタン クラス（簡易デバウンス付き）"""

    def __init__(self, pin, bounce_time=0.01):
        """
        Args:
            pin (int): BCM モードの GPIO ピン番号
            bounce_time (float): デバウンス時間（秒）
        """
        self.pin = pin
        self.bounce_time = bounce_time
        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    def is_pressed(self):
        """
        Returns:
            bool: 押下検知時に True を返す
        """
        if GPIO.input(self.pin) == GPIO.HIGH:
            time.sleep(self.bounce_time)
            if GPIO.input(self.pin) == GPIO.HIGH:
                return True
        return False


class Programmer:
    """pymcuprog で ATtiny1616 を UPDI 経由で書き込むクラス"""

    def write_hex(self, file_path):
        """
        Args:
            file_path (str): 書き込む .hex ファイルのパス
        Returns:
            bool: 成功時 True、失敗時 False
        """
        cmd = [
            "pymcuprog", "write",
            "-t", "uart",
            "-u", "/dev/ttyAMA0",
            "-d", "attiny1616",
            "-f", file_path,
            "--erase",
            "--verify",
        ]
        # デバッグ用: 実行コマンドを表示
        print(f"実行コマンド: {' '.join(cmd)}")
        # コマンド実行 (出力をキャプチャ)
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            print("プログラミングエラー:")
            if result.stdout:
                print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            return False
        return True


def main():
    # GPIO 初期化
    GPIO.setmode(GPIO.BCM)

    # ハードウェアオブジェクト生成
    green_led = LED(22)
    yellow_led = LED(27)
    buzzer = Buzzer(23)
    button = Button(24)
    programmer = Programmer()

    # 起動時状態: 緑 LED 点灯
    green_led.on()
    yellow_led.off()

    try:
        while True:
            if button.is_pressed():
                # 書込み開始
                green_led.off()
                yellow_led.on()

                # hex ファイル検出
                base_dir = os.path.dirname(os.path.abspath(__file__))
                hex_dir = os.path.join(base_dir, "hex")
                os.makedirs(hex_dir, exist_ok=True)
                hex_files = glob.glob(os.path.join(hex_dir, "*.hex"))

                if not hex_files:
                    print("./hex に .hex ファイルが見つかりません。")
                else:
                    target = hex_files[0]
                    programmer.write_hex(target)

                # 書込み後処理
                yellow_led.off()
                buzzer.buzz(1.0)
                green_led.on()

            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    main()
