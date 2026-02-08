"""
Sprite Toolkit - Unified application for sprite animation and manipulation
Combines Coin Spin Animator, Spritesheet Splitter, and Spritesheet to GIF Converter
ENHANCED VERSION with FPS/MS toggle and fixed GIF export
"""

import sys
import os
import numpy as np
from pathlib import Path
from PIL import Image, ImageQt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, 
    QFileDialog, QVBoxLayout, QHBoxLayout, QSlider, QMessageBox, 
    QSpinBox, QRadioButton, QButtonGroup, QGroupBox, QGridLayout,
    QTabWidget, QLineEdit, QProgressBar, QFrame, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject
from PySide6.QtGui import QPixmap, QIcon
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import multiprocessing


class SplitterWorker(QObject):
    """Worker for splitting spritesheet in a separate thread"""
    progress = Signal(int)
    finished = Signal(int, str)
    error = Signal(str)
    
    def __init__(self, spritesheet, frame_w, frame_h, output_dir, prefix, start, pad):
        super().__init__()
        self.spritesheet = spritesheet
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.output_dir = output_dir
        self.prefix = prefix
        self.start = start
        self.pad = pad
        self._should_stop = False
    
    def stop(self):
        """Request the worker to stop"""
        self._should_stop = True
    
    def is_frame_empty(self, frame):
        """Check if a frame is empty (fully transparent or uniform color)"""
        try:
            # Convert to RGBA if needed
            if frame.mode != 'RGBA':
                frame_rgba = frame.convert('RGBA')
            else:
                frame_rgba = frame
            
            # Get the alpha channel
            alpha = frame_rgba.split()[-1]
            alpha_data = alpha.getdata()
            
            # Check if completely transparent
            if max(alpha_data) == 0:
                return True
            
            # Get pixel data
            pixels = list(frame_rgba.getdata())
            
            # Check if all non-transparent pixels are the same color
            non_transparent = [p for p in pixels if p[3] > 10]  # Alpha > 10
            
            if len(non_transparent) == 0:
                return True
            
            # If less than 1% of pixels are non-transparent, consider empty
            total_pixels = frame.width * frame.height
            if len(non_transparent) < total_pixels * 0.01:
                return True
            
            return False
            
        except Exception as e:
            print(f"Error checking if frame is empty: {e}")
            return False
    
    def save_frame(self, args):
        """Worker function for parallel frame saving"""
        if self._should_stop:
            return False
        try:
            spritesheet, left, top, right, bottom, output_path = args
            frame = spritesheet.crop((left, top, right, bottom))
            
            # Skip empty frames
            if self.is_frame_empty(frame):
                return False
            
            frame.save(output_path, "PNG", optimize=False)
            return True
        except Exception as e:
            print(f"Error saving frame: {e}")
            return False
    
    def run(self):
        try:
            sheet_width, sheet_height = self.spritesheet.size
            
            frames_x = sheet_width // self.frame_w
            frames_y = sheet_height // self.frame_h
            total = frames_x * frames_y
            
            if total == 0:
                self.error.emit("Frame dimensions are larger than spritesheet size")
                return
            
            # Create output directory
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
            if total > 100:
                # Use parallel processing for large spritesheets
                tasks = []
                for row in range(frames_y):
                    for col in range(frames_x):
                        if self._should_stop:
                            self.error.emit("Operation cancelled")
                            return
                        
                        left = col * self.frame_w
                        top = row * self.frame_h
                        right = left + self.frame_w
                        bottom = top + self.frame_h
                        
                        num = self.start + (row * frames_x + col)
                        filename = f"{self.prefix}_{str(num).zfill(self.pad)}.png"
                        output_path = self.output_dir / filename
                        
                        tasks.append((self.spritesheet, left, top, right, bottom, output_path))
                
                max_workers = min(multiprocessing.cpu_count() * 2, 16)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    completed = 0
                    saved = 0
                    for result in executor.map(self.save_frame, tasks):
                        if self._should_stop:
                            executor.shutdown(wait=False, cancel_futures=True)
                            self.error.emit("Operation cancelled")
                            return
                        completed += 1
                        if result:
                            saved += 1
                        progress_pct = int((completed / total) * 100)
                        self.progress.emit(progress_pct)
                
                count = saved
            else:
                # Sequential processing for small spritesheets
                count = 0
                frame_num = 0
                for row in range(frames_y):
                    for col in range(frames_x):
                        if self._should_stop:
                            self.error.emit("Operation cancelled")
                            return
                        
                        left = col * self.frame_w
                        top = row * self.frame_h
                        right = left + self.frame_w
                        bottom = top + self.frame_h
                        
                        frame = self.spritesheet.crop((left, top, right, bottom))
                        
                        # Skip empty frames
                        if not self.is_frame_empty(frame):
                            num = self.start + count
                            filename = f"{self.prefix}_{str(num).zfill(self.pad)}.png"
                            frame.save(self.output_dir / filename, "PNG", optimize=False)
                            count += 1
                        
                        frame_num += 1
                        progress_pct = int((frame_num / total) * 100)
                        self.progress.emit(progress_pct)
            
            self.finished.emit(count, str(self.output_dir))
            
        except Exception as e:
            self.error.emit(str(e))


class CoinAnimatorTab(QWidget):
    """Tab for coin spin animation"""
    
    def __init__(self):
        super().__init__()
        self.image = None
        self.frames = []
        self.frame_index = 0
        self.total_frames = 60
        self.fps = 30
        self.ms_per_frame = 1000 / 30  # ~33.33ms
        self.use_fps = True  # True for FPS mode, False for MS mode
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)
        
        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Preview Section
        preview_container = QFrame()
        preview_container.setFrameStyle(QFrame.StyledPanel)
        preview_container.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2d2d2d, stop:1 #1a1a1a
                );
                border-radius: 10px;
            }
        """)
        preview_layout = QVBoxLayout(preview_container)
        
        preview_label = QLabel("Preview")
        preview_label.setStyleSheet("color: #aaa; font-size: 14px; font-weight: bold;")
        preview_label.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(preview_label)
        
        self.preview = QLabel("Load an image to begin")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("""
            background: #1a1a1a;
            color: #666;
            border-radius: 8px;
            font-size: 13px;
        """)
        self.preview.setMinimumSize(500, 400)
        preview_layout.addWidget(self.preview)
        
        layout.addWidget(preview_container, 3)
        
        # Controls Section
        controls_container = self.create_controls()
        layout.addWidget(controls_container, 2)
    
    def create_controls(self):
        """Create the controls panel"""
        controls = QFrame()
        controls.setFrameStyle(QFrame.StyledPanel)
        controls.setStyleSheet("""
            QFrame {
                background: #2d2d2d;
                border-radius: 10px;
            }
        """)
        
        controls_layout = QVBoxLayout(controls)
        controls_layout.setSpacing(15)
        controls_layout.setContentsMargins(15, 15, 15, 15)
        
        # Load Image Button
        load_btn = QPushButton("📁 Load Image")
        load_btn.clicked.connect(self.load_image)
        controls_layout.addWidget(load_btn)
        
        # Animation Settings Group
        anim_group = QGroupBox("Animation Settings")
        anim_layout = QVBoxLayout()
        
        # Frames
        frames_layout = QGridLayout()
        frames_layout.addWidget(QLabel("Frame Count:"), 0, 0)
        self.frames_label = QLabel(str(self.total_frames))
        self.frames_label.setStyleSheet("color: #5d9cec; font-weight: bold;")
        frames_layout.addWidget(self.frames_label, 0, 1, Qt.AlignRight)
        
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setRange(20, 180)
        self.frame_slider.setValue(self.total_frames)
        self.frame_slider.valueChanged.connect(self.update_frame_count)
        frames_layout.addWidget(self.frame_slider, 1, 0, 1, 2)
        
        anim_layout.addLayout(frames_layout)
        
        # Speed Control Mode Toggle
        speed_mode_layout = QHBoxLayout()
        speed_mode_layout.addWidget(QLabel("Speed Mode:"))
        
        self.speed_mode_group = QButtonGroup()
        self.fps_radio = QRadioButton("FPS")
        self.ms_radio = QRadioButton("Milliseconds")
        self.fps_radio.setChecked(True)
        
        self.speed_mode_group.addButton(self.fps_radio)
        self.speed_mode_group.addButton(self.ms_radio)
        
        self.fps_radio.toggled.connect(self.toggle_speed_mode)
        
        speed_mode_layout.addWidget(self.fps_radio)
        speed_mode_layout.addWidget(self.ms_radio)
        speed_mode_layout.addStretch()
        anim_layout.addLayout(speed_mode_layout)
        
        # FPS Control
        self.fps_layout = QGridLayout()
        self.fps_layout.addWidget(QLabel("FPS:"), 0, 0)
        
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(1, 120)
        self.fps_spinbox.setValue(self.fps)
        self.fps_spinbox.valueChanged.connect(self.update_fps)
        self.fps_layout.addWidget(self.fps_spinbox, 0, 1)
        
        anim_layout.addLayout(self.fps_layout)
        
        # MS Control (initially hidden)
        self.ms_layout = QGridLayout()
        self.ms_layout.addWidget(QLabel("Milliseconds:"), 0, 0)
        
        self.ms_spinbox = QDoubleSpinBox()
        self.ms_spinbox.setRange(8.33, 1000.0)  # 120 FPS to 1 FPS
        self.ms_spinbox.setDecimals(2)
        self.ms_spinbox.setSingleStep(1.0)
        self.ms_spinbox.setValue(self.ms_per_frame)
        self.ms_spinbox.valueChanged.connect(self.update_ms)
        self.ms_layout.addWidget(self.ms_spinbox, 0, 1)
        
        # Hide MS controls initially
        self.ms_spinbox.setVisible(False)
        for i in range(self.ms_layout.count()):
            item = self.ms_layout.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(False)
        
        anim_layout.addLayout(self.ms_layout)
        
        anim_group.setLayout(anim_layout)
        controls_layout.addWidget(anim_group)
        
        # Playback Controls
        self.play_pause_btn = QPushButton("▶ Play")
        self.play_pause_btn.clicked.connect(self.toggle_playback)
        self.play_pause_btn.setEnabled(False)
        controls_layout.addWidget(self.play_pause_btn)
        
        # Export Group
        export_group = QGroupBox("Export")
        export_layout = QVBoxLayout()
        
        export_gif = QPushButton("💾 Export GIF")
        export_gif.clicked.connect(self.export_gif)
        export_layout.addWidget(export_gif)
        
        export_sheet = QPushButton("🖼 Export Spritesheet")
        export_sheet.clicked.connect(self.export_spritesheet)
        export_layout.addWidget(export_sheet)
        
        export_group.setLayout(export_layout)
        controls_layout.addWidget(export_group)
        
        controls_layout.addStretch()
        
        return controls
    
    def toggle_speed_mode(self, checked):
        """Toggle between FPS and MS mode"""
        if checked:  # FPS mode selected
            self.use_fps = True
            # Show FPS controls
            self.fps_spinbox.setVisible(True)
            for i in range(self.fps_layout.count()):
                item = self.fps_layout.itemAt(i)
                if item and item.widget():
                    item.widget().setVisible(True)
            
            # Hide MS controls
            self.ms_spinbox.setVisible(False)
            for i in range(self.ms_layout.count()):
                item = self.ms_layout.itemAt(i)
                if item and item.widget() and item.widget() != self.ms_spinbox:
                    item.widget().setVisible(False)
        else:  # MS mode selected
            self.use_fps = False
            # Hide FPS controls
            self.fps_spinbox.setVisible(False)
            for i in range(self.fps_layout.count()):
                item = self.fps_layout.itemAt(i)
                if item and item.widget() and item.widget() != self.fps_spinbox:
                    item.widget().setVisible(False)
            
            # Show MS controls
            self.ms_spinbox.setVisible(True)
            for i in range(self.ms_layout.count()):
                item = self.ms_layout.itemAt(i)
                if item and item.widget():
                    item.widget().setVisible(True)
    
    def update_fps(self, value):
        """Update FPS - this controls animation playback speed"""
        self.fps = value
        self.ms_per_frame = 1000.0 / value
        
        # Update MS spinbox without triggering its signal
        self.ms_spinbox.blockSignals(True)
        self.ms_spinbox.setValue(self.ms_per_frame)
        self.ms_spinbox.blockSignals(False)
        
        # Update timer if running
        if self.timer.isActive():
            self.timer.stop()
            interval = int(self.ms_per_frame)
            self.timer.start(interval)
    
    def update_ms(self, value):
        """Update milliseconds per frame"""
        self.ms_per_frame = value
        self.fps = 1000.0 / value
        
        # Update FPS spinbox without triggering its signal
        self.fps_spinbox.blockSignals(True)
        self.fps_spinbox.setValue(int(round(self.fps)))
        self.fps_spinbox.blockSignals(False)
        
        # Update timer if running
        if self.timer.isActive():
            self.timer.stop()
            interval = int(self.ms_per_frame)
            self.timer.start(interval)
    
    def update_frame_count(self, value):
        """Update the number of frames in the animation"""
        self.total_frames = value
        self.frames_label.setText(str(value))
        if self.image:
            self.generate_frames()
            self.show_frame(0)
    
    def load_image(self):
        """Load an image for animation"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "", "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        
        try:
            # Close existing image if any
            if self.image:
                try:
                    self.image.close()
                except:
                    pass
            
            self.image = Image.open(path).convert("RGBA")
            self.generate_frames()
            self.show_frame(0)
            self.play_pause_btn.setEnabled(True)
            self.play()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load image:\n{str(e)}")
    
    def generate_frames(self):
        """Generate frames for horizontal coin spin animation"""
        if not self.image:
            return
        
        try:
            self.frames = []
            w, h = self.image.size
            
            for i in range(self.total_frames):
                # Calculate angle for full rotation (0 to 2π)
                angle = 2 * np.pi * i / self.total_frames
                
                # Horizontal compression based on cosine (simulates 3D rotation)
                scale_x = np.cos(angle)
                
                # Use absolute value for width calculation
                abs_scale_x = max(abs(scale_x), 0.01)  # Minimum width to avoid invisible frames
                
                # Calculate new width, keep height the same
                new_w = max(1, int(w * abs_scale_x))
                
                # Resize with horizontal compression only
                frame = self.image.resize((new_w, h), Image.Resampling.LANCZOS)
                
                # Flip horizontally when on the back side of the coin
                if scale_x < 0:
                    frame = frame.transpose(Image.FLIP_LEFT_RIGHT)
                
                self.frames.append(frame)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate frames:\n{str(e)}")
            self.frames = []
    
    def show_frame(self, index):
        """Display a specific frame"""
        if not self.frames or index >= len(self.frames):
            return
        
        try:
            qt_img = ImageQt.ImageQt(self.frames[index])
            pix = QPixmap.fromImage(qt_img)
            self.preview.setPixmap(
                pix.scaled(
                    self.preview.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            )
        except Exception as e:
            print(f"Error displaying frame: {e}")
    
    def next_frame(self):
        """Advance to the next frame"""
        if self.frames:
            self.frame_index = (self.frame_index + 1) % len(self.frames)
            self.show_frame(self.frame_index)
    
    def toggle_playback(self):
        """Toggle animation playback"""
        if not self.frames:
            return
        
        if self.timer.isActive():
            self.timer.stop()
            self.play_pause_btn.setText("▶ Play")
        else:
            interval = int(self.ms_per_frame)
            self.timer.start(interval)
            self.play_pause_btn.setText("⏸ Pause")
    
    def play(self):
        """Start animation playback"""
        if not self.frames:
            return
        interval = int(self.ms_per_frame)
        self.timer.start(interval)
        self.play_pause_btn.setText("⏸ Pause")
    
    def stop(self):
        """Stop animation playback"""
        self.timer.stop()
        self.play_pause_btn.setText("▶ Play")
    
    def pause_on_hide(self):
        """Pause animation when tab is hidden"""
        if self.timer.isActive():
            self.stop()
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop()
        if self.image:
            try:
                self.image.close()
            except:
                pass
        self.frames = []
    
    def estimate_gif_size(self, frames, duration):
        """Estimate the file size of the GIF in MB"""
        try:
            # Find max dimensions
            max_width = max(f.width for f in frames)
            max_height = max(f.height for f in frames)
            
            # Rough estimation: 
            # Each frame in palette mode ≈ width × height bytes (with compression)
            # Plus GIF header overhead
            pixels_per_frame = max_width * max_height
            
            # GIF with palette mode and LZW compression typically achieves
            # 30-50% of raw size for sprite animations
            bytes_per_frame = pixels_per_frame * 0.4
            
            total_bytes = bytes_per_frame * len(frames)
            total_bytes += 2048  # Header and metadata overhead
            
            # Convert to MB
            size_mb = total_bytes / (1024 * 1024)
            
            return size_mb
        except:
            return 0.0
    
    def export_gif(self):
        """Export animation as GIF with proper transparency and timing"""
        if not self.frames:
            QMessageBox.warning(self, "No Frames", "Please load an image first!")
            return
        
        # Estimate file size
        duration = int(round(self.ms_per_frame))
        estimated_size = self.estimate_gif_size(self.frames, duration)
        
        timestamp = datetime.now().strftime("%H%M%S")
        default_name = f"spin_{timestamp}.gif"
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Export GIF", default_name, "GIF (*.gif)"
        )
        if not path:
            return
        
        # Normalize extension
        if not path.lower().endswith('.gif'):
            path += '.gif'
        
        try:
            # Find maximum dimensions across all frames
            max_width = max(f.width for f in self.frames)
            max_height = max(f.height for f in self.frames)
            
            # Prepare frames for GIF export
            # All frames must be centered on the same canvas size
            export_frames = []
            
            for frame in self.frames:
                # Create a canvas of max size with transparency
                canvas = Image.new('RGBA', (max_width, max_height), (0, 0, 0, 0))
                
                # Center the frame on the canvas
                x_offset = (max_width - frame.width) // 2
                y_offset = (max_height - frame.height) // 2
                canvas.paste(frame, (x_offset, y_offset), frame)
                
                # Convert RGBA canvas to P mode with transparency
                if canvas.mode == 'RGBA':
                    # Create an alpha mask
                    alpha = canvas.split()[-1]
                    # Convert to RGB first with transparent background
                    rgb_frame = Image.new('RGB', canvas.size, (255, 255, 255))
                    rgb_frame.paste(canvas, mask=alpha)
                    # Convert to palette mode with transparency
                    p_frame = rgb_frame.convert('P', palette=Image.ADAPTIVE, colors=255)
                    # Set transparency index
                    p_frame.info['transparency'] = 255
                    export_frames.append(p_frame)
                else:
                    export_frames.append(canvas.convert('P', palette=Image.ADAPTIVE))
            
            # Save with proper settings
            export_frames[0].save(
                path,
                save_all=True,
                append_images=export_frames[1:],
                duration=duration,  # Use exact ms per frame
                loop=0,  # Infinite loop
                disposal=2,  # Restore to background
                optimize=False  # Don't optimize to preserve timing accuracy
            )
            
            # Get actual file size
            actual_size = os.path.getsize(path) / (1024 * 1024)
            
            QMessageBox.information(
                self, "✓ Exported", 
                f"GIF exported successfully!\n"
                f"{os.path.basename(path)}\n\n"
                f"Size: {max_width}×{max_height}px\n"
                f"Frames: {len(self.frames)}\n"
                f"Timing: {duration}ms per frame ({self.fps:.1f} FPS)\n"
                f"File size: {actual_size:.2f} MB"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export GIF:\n{str(e)}")
    
    def export_spritesheet(self):
        """Export frames as a spritesheet"""
        if not self.frames:
            QMessageBox.warning(self, "No Frames", "Please load an image first!")
            return
        
        timestamp = datetime.now().strftime("%H%M%S")
        default_name = f"sheet_{timestamp}.png"
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Spritesheet", default_name, "PNG (*.png)"
        )
        if not path:
            return
        
        # Normalize extension
        if not path.lower().endswith('.png'):
            path += '.png'
        
        try:
            # Calculate grid dimensions
            num_frames = len(self.frames)
            cols = int(np.ceil(np.sqrt(num_frames)))
            rows = int(np.ceil(num_frames / cols))
            
            max_w = max(f.width for f in self.frames)
            max_h = max(f.height for f in self.frames)
            
            sheet_width = max_w * cols
            sheet_height = max_h * rows
            
            sheet = Image.new(
                "RGBA",
                (sheet_width, sheet_height),
                (0, 0, 0, 0)
            )
            
            for i, frame in enumerate(self.frames):
                row = i // cols
                col = i % cols
                
                # Center each frame in its cell
                x_offset = (max_w - frame.width) // 2
                y_offset = (max_h - frame.height) // 2
                
                x_pos = col * max_w + x_offset
                y_pos = row * max_h + y_offset
                
                sheet.paste(frame, (x_pos, y_pos), frame)
            
            sheet.save(path)
            
            # Get actual file size
            actual_size = os.path.getsize(path) / (1024 * 1024)
            
            QMessageBox.information(
                self, "✓ Exported",
                f"Spritesheet exported successfully!\n"
                f"{os.path.basename(path)}\n\n"
                f"Size: {sheet_width}×{sheet_height}px\n"
                f"Grid: {cols}×{rows} ({num_frames} frames)\n"
                f"File size: {actual_size:.2f} MB"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export spritesheet:\n{str(e)}")


class SheetToGifTab(QWidget):
    """Tab for converting spritesheet to GIF"""
    
    def __init__(self):
        super().__init__()
        
        self.spritesheet = None
        self.spritesheet_path = ""
        self.frames = []
        self.frame_index = 0
        
        # Frame settings
        self.frame_width = 32
        self.frame_height = 32
        self.frames_x = 0
        self.frames_y = 0
        
        # Animation settings
        self.fps = 12
        self.ms_per_frame = 1000 / 12  # ~83.33ms
        self.use_fps = True
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)
        
        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Preview Section
        preview_container = QFrame()
        preview_container.setFrameStyle(QFrame.StyledPanel)
        preview_container.setStyleSheet("""
            QFrame {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2d2d2d, stop:1 #1a1a1a
                );
                border-radius: 10px;
            }
        """)
        preview_layout = QVBoxLayout(preview_container)
        
        preview_label = QLabel("Animation Preview")
        preview_label.setStyleSheet("color: #aaa; font-size: 14px; font-weight: bold;")
        preview_label.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(preview_label)
        
        self.preview = QLabel("Load a spritesheet to begin")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("""
            background: #1a1a1a;
            color: #666;
            border-radius: 8px;
            font-size: 13px;
        """)
        self.preview.setMinimumSize(500, 400)
        preview_layout.addWidget(self.preview)
        
        layout.addWidget(preview_container, 3)
        
        # Controls Section
        controls_container = self.create_controls()
        layout.addWidget(controls_container, 2)
    
    def create_controls(self):
        """Create the controls panel"""
        controls = QFrame()
        controls.setFrameStyle(QFrame.StyledPanel)
        controls.setStyleSheet("""
            QFrame {
                background: #2d2d2d;
                border-radius: 10px;
            }
        """)
        
        controls_layout = QVBoxLayout(controls)
        controls_layout.setSpacing(15)
        controls_layout.setContentsMargins(15, 15, 15, 15)
        
        # Load Spritesheet Button
        load_btn = QPushButton("📁 Load Spritesheet")
        load_btn.clicked.connect(self.load_spritesheet)
        controls_layout.addWidget(load_btn)
        
        # Frame Dimensions Group
        dims_group = QGroupBox("Frame Dimensions")
        dims_layout = QGridLayout()
        
        dims_layout.addWidget(QLabel("Width:"), 0, 0)
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(1, 10000)
        self.width_spinbox.setValue(self.frame_width)
        self.width_spinbox.valueChanged.connect(self.update_frame_width)
        dims_layout.addWidget(self.width_spinbox, 0, 1)
        
        dims_layout.addWidget(QLabel("Height:"), 1, 0)
        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(1, 10000)
        self.height_spinbox.setValue(self.frame_height)
        self.height_spinbox.valueChanged.connect(self.update_frame_height)
        dims_layout.addWidget(self.height_spinbox, 1, 1)
        
        extract_btn = QPushButton("Extract Frames")
        extract_btn.clicked.connect(self.extract_frames)
        dims_layout.addWidget(extract_btn, 2, 0, 1, 2)
        
        dims_group.setLayout(dims_layout)
        controls_layout.addWidget(dims_group)
        
        # Info Label
        self.info_label = QLabel("No spritesheet loaded")
        self.info_label.setStyleSheet("color: #5d9cec;")
        self.info_label.setWordWrap(True)
        controls_layout.addWidget(self.info_label)
        
        # Animation Settings Group
        anim_group = QGroupBox("Animation Settings")
        anim_layout = QVBoxLayout()
        
        # Speed Mode Toggle
        speed_mode_layout = QHBoxLayout()
        speed_mode_layout.addWidget(QLabel("Speed Mode:"))
        
        self.speed_mode_group = QButtonGroup()
        self.fps_radio = QRadioButton("FPS")
        self.ms_radio = QRadioButton("Milliseconds")
        self.fps_radio.setChecked(True)
        
        self.speed_mode_group.addButton(self.fps_radio)
        self.speed_mode_group.addButton(self.ms_radio)
        
        self.fps_radio.toggled.connect(self.toggle_speed_mode)
        
        speed_mode_layout.addWidget(self.fps_radio)
        speed_mode_layout.addWidget(self.ms_radio)
        speed_mode_layout.addStretch()
        anim_layout.addLayout(speed_mode_layout)
        
        # FPS Control
        self.fps_layout = QGridLayout()
        self.fps_layout.addWidget(QLabel("FPS:"), 0, 0)
        
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(1, 120)
        self.fps_spinbox.setValue(self.fps)
        self.fps_spinbox.valueChanged.connect(self.update_fps)
        self.fps_layout.addWidget(self.fps_spinbox, 0, 1)
        
        anim_layout.addLayout(self.fps_layout)
        
        # MS Control (initially hidden)
        self.ms_layout = QGridLayout()
        self.ms_layout.addWidget(QLabel("Milliseconds:"), 0, 0)
        
        self.ms_spinbox = QDoubleSpinBox()
        self.ms_spinbox.setRange(8.33, 1000.0)
        self.ms_spinbox.setDecimals(2)
        self.ms_spinbox.setSingleStep(1.0)
        self.ms_spinbox.setValue(self.ms_per_frame)
        self.ms_spinbox.valueChanged.connect(self.update_ms)
        self.ms_layout.addWidget(self.ms_spinbox, 0, 1)
        
        # Hide MS controls initially
        self.ms_spinbox.setVisible(False)
        for i in range(self.ms_layout.count()):
            item = self.ms_layout.itemAt(i)
            if item and item.widget():
                item.widget().setVisible(False)
        
        anim_layout.addLayout(self.ms_layout)
        
        anim_group.setLayout(anim_layout)
        controls_layout.addWidget(anim_group)
        
        # Playback Controls
        self.play_pause_btn = QPushButton("▶ Play")
        self.play_pause_btn.clicked.connect(self.toggle_playback)
        self.play_pause_btn.setEnabled(False)
        controls_layout.addWidget(self.play_pause_btn)
        
        # Export Button
        self.export_btn = QPushButton("💾 Export GIF")
        self.export_btn.clicked.connect(self.export_gif)
        self.export_btn.setEnabled(False)
        controls_layout.addWidget(self.export_btn)
        
        controls_layout.addStretch()
        
        return controls
    
    def toggle_speed_mode(self, checked):
        """Toggle between FPS and MS mode"""
        if checked:  # FPS mode selected
            self.use_fps = True
            # Show FPS controls
            self.fps_spinbox.setVisible(True)
            for i in range(self.fps_layout.count()):
                item = self.fps_layout.itemAt(i)
                if item and item.widget():
                    item.widget().setVisible(True)
            
            # Hide MS controls
            self.ms_spinbox.setVisible(False)
            for i in range(self.ms_layout.count()):
                item = self.ms_layout.itemAt(i)
                if item and item.widget() and item.widget() != self.ms_spinbox:
                    item.widget().setVisible(False)
        else:  # MS mode selected
            self.use_fps = False
            # Hide FPS controls
            self.fps_spinbox.setVisible(False)
            for i in range(self.fps_layout.count()):
                item = self.fps_layout.itemAt(i)
                if item and item.widget() and item.widget() != self.fps_spinbox:
                    item.widget().setVisible(False)
            
            # Show MS controls
            self.ms_spinbox.setVisible(True)
            for i in range(self.ms_layout.count()):
                item = self.ms_layout.itemAt(i)
                if item and item.widget():
                    item.widget().setVisible(True)
    
    def update_fps(self, value):
        """Update FPS"""
        self.fps = value
        self.ms_per_frame = 1000.0 / value
        
        # Update MS spinbox without triggering its signal
        self.ms_spinbox.blockSignals(True)
        self.ms_spinbox.setValue(self.ms_per_frame)
        self.ms_spinbox.blockSignals(False)
        
        # Update timer if running
        if self.timer.isActive():
            self.timer.stop()
            interval = int(self.ms_per_frame)
            self.timer.start(interval)
    
    def update_ms(self, value):
        """Update milliseconds per frame"""
        self.ms_per_frame = value
        self.fps = 1000.0 / value
        
        # Update FPS spinbox without triggering its signal
        self.fps_spinbox.blockSignals(True)
        self.fps_spinbox.setValue(int(round(self.fps)))
        self.fps_spinbox.blockSignals(False)
        
        # Update timer if running
        if self.timer.isActive():
            self.timer.stop()
            interval = int(self.ms_per_frame)
            self.timer.start(interval)
    
    def update_frame_width(self, value):
        self.frame_width = value
    
    def update_frame_height(self, value):
        self.frame_height = value
    
    def infer_frame_dimensions(self, width, height):
        """Intelligently infer frame dimensions from spritesheet"""
        # Common sprite sizes (powers of 2 and common values)
        common_sizes = [8, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512]
        
        # Try to find common divisors
        best_w = 32  # Default
        best_h = 32
        
        # Check if width/height are divisible by common sizes
        for size in reversed(common_sizes):
            if width % size == 0 and height % size == 0:
                # Perfect square frames possible
                best_w = size
                best_h = size
                break
            elif width % size == 0 and height >= size:
                # Width fits, check if height works
                if height % size == 0:
                    best_w = size
                    best_h = size
                    break
        
        # If no perfect match, try rectangular frames
        if best_w == 32 and best_h == 32:
            for w_size in reversed(common_sizes):
                if width % w_size == 0:
                    best_w = w_size
                    # Find best height
                    for h_size in reversed(common_sizes):
                        if height % h_size == 0:
                            best_h = h_size
                            break
                    break
        
        # Sanity check - don't suggest frames larger than the image
        if best_w > width:
            best_w = width
        if best_h > height:
            best_h = height
        
        return best_w, best_h
    
    def load_spritesheet(self):
        """Load a spritesheet image"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Spritesheet", "", 
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff);;All Files (*.*)"
        )
        if not path:
            return
        
        try:
            # Close existing spritesheet if any
            if self.spritesheet:
                try:
                    self.spritesheet.close()
                except:
                    pass
            
            self.spritesheet = Image.open(path)
            self.spritesheet_path = path
            
            width, height = self.spritesheet.size
            
            # Auto-infer frame dimensions
            inferred_w, inferred_h = self.infer_frame_dimensions(width, height)
            
            # Update spinboxes with inferred values
            self.width_spinbox.setValue(inferred_w)
            self.height_spinbox.setValue(inferred_h)
            self.frame_width = inferred_w
            self.frame_height = inferred_h
            
            # Calculate how many frames this would give
            frames_x = width // inferred_w
            frames_y = height // inferred_h
            total = frames_x * frames_y
            
            self.info_label.setText(
                f"Loaded: {width}×{height}px\n"
                f"Auto-detected: {inferred_w}×{inferred_h}px frames\n"
                f"Would extract {total} frames ({frames_x}×{frames_y})\n"
                f"Adjust if needed, then click 'Extract Frames'"
            )
            
            # Stop any playing animation
            self.stop()
            self.frames = []
            self.play_pause_btn.setEnabled(False)
            self.export_btn.setEnabled(False)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load spritesheet:\n{str(e)}")
    
    def is_frame_empty(self, frame):
        """Check if a frame is empty (fully transparent or uniform color)"""
        try:
            # Convert to RGBA if needed
            if frame.mode != 'RGBA':
                frame = frame.convert('RGBA')
            
            # Get the alpha channel
            alpha = frame.split()[-1]
            alpha_data = alpha.getdata()
            
            # Check if completely transparent
            if max(alpha_data) == 0:
                return True
            
            # Get pixel data
            pixels = list(frame.getdata())
            
            # Check if all non-transparent pixels are the same color
            # (indicates empty/background frame)
            non_transparent = [p for p in pixels if p[3] > 10]  # Alpha > 10
            
            if len(non_transparent) == 0:
                return True
            
            # If less than 1% of pixels are non-transparent, consider empty
            total_pixels = frame.width * frame.height
            if len(non_transparent) < total_pixels * 0.01:
                return True
            
            return False
            
        except Exception as e:
            print(f"Error checking if frame is empty: {e}")
            return False
    
    def extract_frames(self):
        """Extract frames from the spritesheet"""
        if not self.spritesheet:
            QMessageBox.warning(self, "No Spritesheet", "Please load a spritesheet first!")
            return
        
        try:
            width, height = self.spritesheet.size
            
            self.frames_x = width // self.frame_width
            self.frames_y = height // self.frame_height
            total = self.frames_x * self.frames_y
            
            if total == 0:
                QMessageBox.critical(self, "Error", "Frame dimensions are larger than spritesheet!")
                return
            
            # Extract frames
            self.frames = []
            empty_count = 0
            
            for row in range(self.frames_y):
                for col in range(self.frames_x):
                    left = col * self.frame_width
                    top = row * self.frame_height
                    right = left + self.frame_width
                    bottom = top + self.frame_height
                    
                    frame = self.spritesheet.crop((left, top, right, bottom))
                    
                    # Check if frame is empty
                    if self.is_frame_empty(frame):
                        empty_count += 1
                        continue  # Skip empty frames
                    
                    self.frames.append(frame.copy())
            
            if len(self.frames) == 0:
                QMessageBox.warning(
                    self, "No Valid Frames",
                    "All extracted frames appear to be empty!\nTry adjusting frame dimensions."
                )
                return
            
            info_text = f"Extracted {len(self.frames)} frames\n"
            info_text += f"Grid: {self.frames_x}×{self.frames_y}\n"
            info_text += f"Frame size: {self.frame_width}×{self.frame_height}px"
            
            if empty_count > 0:
                info_text += f"\n⚠ Skipped {empty_count} empty frames"
            
            self.info_label.setText(info_text)
            
            # Enable controls and start preview
            self.play_pause_btn.setEnabled(True)
            self.export_btn.setEnabled(True)
            self.frame_index = 0
            self.show_frame(0)
            self.play()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to extract frames:\n{str(e)}")
    
    def show_frame(self, index):
        """Display a specific frame"""
        if not self.frames or index >= len(self.frames):
            return
        
        try:
            frame = self.frames[index]
            qt_img = ImageQt.ImageQt(frame)
            pix = QPixmap.fromImage(qt_img)
            self.preview.setPixmap(
                pix.scaled(
                    self.preview.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            )
        except Exception as e:
            print(f"Error displaying frame: {e}")
    
    def next_frame(self):
        """Advance to the next frame"""
        if self.frames:
            self.frame_index = (self.frame_index + 1) % len(self.frames)
            self.show_frame(self.frame_index)
    
    def toggle_playback(self):
        """Toggle animation playback"""
        if not self.frames:
            return
        
        if self.timer.isActive():
            self.timer.stop()
            self.play_pause_btn.setText("▶ Play")
        else:
            interval = int(self.ms_per_frame)
            self.timer.start(interval)
            self.play_pause_btn.setText("⏸ Pause")
    
    def play(self):
        """Start animation playback"""
        if not self.frames:
            return
        interval = int(self.ms_per_frame)
        self.timer.start(interval)
        self.play_pause_btn.setText("⏸ Pause")
    
    def stop(self):
        """Stop animation playback"""
        self.timer.stop()
        self.play_pause_btn.setText("▶ Play")
    
    def pause_on_hide(self):
        """Pause animation when tab is hidden"""
        if self.timer.isActive():
            self.stop()
    
    def estimate_gif_size(self, frames, duration):
        """Estimate the file size of the GIF in MB"""
        try:
            # Find max dimensions
            max_width = max(f.width for f in frames)
            max_height = max(f.height for f in frames)
            
            # Rough estimation: 
            # Each frame in palette mode ≈ width × height bytes (with compression)
            pixels_per_frame = max_width * max_height
            
            # GIF with palette mode and LZW compression typically achieves
            # 30-50% of raw size for sprite animations
            bytes_per_frame = pixels_per_frame * 0.4
            
            total_bytes = bytes_per_frame * len(frames)
            total_bytes += 2048  # Header and metadata overhead
            
            # Convert to MB
            size_mb = total_bytes / (1024 * 1024)
            
            return size_mb
        except:
            return 0.0
    
    def export_gif(self):
        """Export frames as GIF"""
        if not self.frames:
            QMessageBox.warning(self, "No Frames", "Please extract frames first!")
            return
        
        timestamp = datetime.now().strftime("%H%M%S")
        default_name = f"animation_{timestamp}.gif"
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Export GIF", default_name, "GIF (*.gif)"
        )
        if not path:
            return
        
        if not path.lower().endswith('.gif'):
            path += '.gif'
        
        try:
            # Use exact milliseconds per frame
            duration = int(round(self.ms_per_frame))
            
            # Find maximum dimensions across all frames
            max_width = max(f.width for f in self.frames)
            max_height = max(f.height for f in self.frames)
            
            # Prepare frames for GIF export
            # All frames must be centered on the same canvas size
            export_frames = []
            
            for frame in self.frames:
                # Create a canvas of max size with transparency
                canvas = Image.new('RGBA', (max_width, max_height), (0, 0, 0, 0))
                
                # Center the frame on the canvas
                x_offset = (max_width - frame.width) // 2
                y_offset = (max_height - frame.height) // 2
                canvas.paste(frame, (x_offset, y_offset), frame if frame.mode == 'RGBA' else None)
                
                # Convert to proper mode for GIF
                if canvas.mode == 'RGBA':
                    alpha = canvas.split()[-1]
                    rgb_frame = Image.new('RGB', canvas.size, (255, 255, 255))
                    rgb_frame.paste(canvas, mask=alpha)
                    p_frame = rgb_frame.convert('P', palette=Image.ADAPTIVE, colors=255)
                    p_frame.info['transparency'] = 255
                    export_frames.append(p_frame)
                else:
                    export_frames.append(canvas.convert('P', palette=Image.ADAPTIVE))
            
            # Save GIF
            export_frames[0].save(
                path,
                save_all=True,
                append_images=export_frames[1:],
                duration=duration,
                loop=0,
                disposal=2,
                optimize=False
            )
            
            # Get actual file size
            actual_size = os.path.getsize(path) / (1024 * 1024)
            
            QMessageBox.information(
                self, "✓ Exported",
                f"GIF exported successfully!\n"
                f"{os.path.basename(path)}\n\n"
                f"Size: {max_width}×{max_height}px\n"
                f"Frames: {len(self.frames)}\n"
                f"Timing: {duration}ms per frame ({self.fps:.1f} FPS)\n"
                f"File size: {actual_size:.2f} MB"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export GIF:\n{str(e)}")
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop()
        if self.spritesheet:
            try:
                self.spritesheet.close()
            except:
                pass
        self.frames = []


class SpriteSheetSplitterTab(QWidget):
    """Tab for splitting spritesheets"""
    
    def __init__(self):
        super().__init__()
        
        self.spritesheet_path = ""
        self.output_path = str(Path.home() / "Downloads" / "spritesheet_frames")
        self.frame_width = 32
        self.frame_height = 32
        self.prefix = "frame"
        self.start_index = 0
        self.padding = 4
        
        self.cached_spritesheet = None
        self.cached_path = None
        self.worker_thread = None
        self.worker = None
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("Spritesheet Splitter")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #fff;")
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)
        
        # Spritesheet Selection
        sheet_group = QGroupBox("Spritesheet")
        sheet_layout = QVBoxLayout()
        
        sheet_input_layout = QHBoxLayout()
        self.sheet_path_edit = QLineEdit()
        self.sheet_path_edit.setPlaceholderText("Select a spritesheet image...")
        self.sheet_path_edit.setReadOnly(True)
        sheet_input_layout.addWidget(self.sheet_path_edit)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_spritesheet)
        sheet_input_layout.addWidget(browse_btn)
        
        sheet_layout.addLayout(sheet_input_layout)
        sheet_group.setLayout(sheet_layout)
        main_layout.addWidget(sheet_group)
        
        # Preview Info
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout()
        self.preview_label = QLabel("No spritesheet loaded")
        self.preview_label.setStyleSheet("color: #5d9cec;")
        self.preview_label.setWordWrap(True)
        preview_layout.addWidget(self.preview_label)
        preview_group.setLayout(preview_layout)
        main_layout.addWidget(preview_group)
        
        # Frame Dimensions
        dims_group = QGroupBox("Frame Dimensions")
        dims_layout = QGridLayout()
        
        dims_layout.addWidget(QLabel("Width:"), 0, 0)
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(1, 10000)
        self.width_spinbox.setValue(self.frame_width)
        self.width_spinbox.valueChanged.connect(self.update_frame_width)
        dims_layout.addWidget(self.width_spinbox, 0, 1)
        
        dims_layout.addWidget(QLabel("Height:"), 0, 2)
        self.height_spinbox = QSpinBox()
        self.height_spinbox.setRange(1, 10000)
        self.height_spinbox.setValue(self.frame_height)
        self.height_spinbox.valueChanged.connect(self.update_frame_height)
        dims_layout.addWidget(self.height_spinbox, 0, 3)
        
        calc_btn = QPushButton("Calculate Preview")
        calc_btn.clicked.connect(self.calculate_preview)
        dims_layout.addWidget(calc_btn, 0, 4)
        
        dims_group.setLayout(dims_layout)
        main_layout.addWidget(dims_group)
        
        # Output Settings
        output_group = QGroupBox("Output Settings")
        output_layout = QGridLayout()
        
        output_layout.addWidget(QLabel("Output Folder:"), 0, 0)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setText(self.output_path)
        output_layout.addWidget(self.output_path_edit, 0, 1)
        
        output_browse_btn = QPushButton("Browse...")
        output_browse_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(output_browse_btn, 0, 2)
        
        output_layout.addWidget(QLabel("Filename Prefix:"), 1, 0)
        self.prefix_edit = QLineEdit(self.prefix)
        self.prefix_edit.textChanged.connect(self.update_example)
        output_layout.addWidget(self.prefix_edit, 1, 1)
        
        output_layout.addWidget(QLabel("Start Index:"), 2, 0)
        self.start_index_spinbox = QSpinBox()
        self.start_index_spinbox.setRange(0, 999999)
        self.start_index_spinbox.setValue(self.start_index)
        self.start_index_spinbox.valueChanged.connect(self.update_example)
        output_layout.addWidget(self.start_index_spinbox, 2, 1)
        
        output_layout.addWidget(QLabel("Zero Padding:"), 3, 0)
        self.padding_spinbox = QSpinBox()
        self.padding_spinbox.setRange(1, 10)
        self.padding_spinbox.setValue(self.padding)
        self.padding_spinbox.valueChanged.connect(self.update_example)
        output_layout.addWidget(self.padding_spinbox, 3, 1)
        
        output_group.setLayout(output_layout)
        main_layout.addWidget(output_group)
        
        # Example filename
        self.example_label = QLabel()
        self.example_label.setStyleSheet("color: #888; font-style: italic;")
        self.update_example()
        main_layout.addWidget(self.example_label)
        
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)
        
        # Status Label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #5d9cec;")
        main_layout.addWidget(self.status_label)
        
        # Split Button
        self.split_btn = QPushButton("Split Spritesheet")
        self.split_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
            }
        """)
        self.split_btn.clicked.connect(self.start_split)
        main_layout.addWidget(self.split_btn)
        
        main_layout.addStretch()
    
    def update_frame_width(self, value):
        self.frame_width = value
    
    def update_frame_height(self, value):
        self.frame_height = value
    
    def update_example(self):
        """Update the example filename"""
        try:
            prefix = self.prefix_edit.text() or "frame"
            start = self.start_index_spinbox.value()
            pad = self.padding_spinbox.value()
            example = f"Example: {prefix}_{str(start).zfill(pad)}.png"
            self.example_label.setText(example)
        except:
            self.example_label.setText("Example: Invalid settings")
    
    def infer_frame_dimensions(self, width, height):
        """Intelligently infer frame dimensions from spritesheet"""
        # Common sprite sizes (powers of 2 and common values)
        common_sizes = [8, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512]
        
        # Try to find common divisors
        best_w = 32  # Default
        best_h = 32
        
        # Check if width/height are divisible by common sizes
        for size in reversed(common_sizes):
            if width % size == 0 and height % size == 0:
                # Perfect square frames possible
                best_w = size
                best_h = size
                break
            elif width % size == 0 and height >= size:
                # Width fits, check if height works
                if height % size == 0:
                    best_w = size
                    best_h = size
                    break
        
        # If no perfect match, try rectangular frames
        if best_w == 32 and best_h == 32:
            for w_size in reversed(common_sizes):
                if width % w_size == 0:
                    best_w = w_size
                    # Find best height
                    for h_size in reversed(common_sizes):
                        if height % h_size == 0:
                            best_h = h_size
                            break
                    break
        
        # Sanity check - don't suggest frames larger than the image
        if best_w > width:
            best_w = width
        if best_h > height:
            best_h = height
        
        return best_w, best_h
    
    def browse_spritesheet(self):
        """Browse for a spritesheet image"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Spritesheet",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff);;All Files (*.*)"
        )
        
        if path:
            self.spritesheet_path = path
            self.sheet_path_edit.setText(path)
            # Clear cache when new file selected
            self.clear_cache()
            
            # Try to load and infer dimensions
            try:
                img = self.load_spritesheet()
                width, height = img.size
                
                # Auto-infer frame dimensions
                inferred_w, inferred_h = self.infer_frame_dimensions(width, height)
                
                # Update spinboxes with inferred values
                self.width_spinbox.setValue(inferred_w)
                self.height_spinbox.setValue(inferred_h)
                self.frame_width = inferred_w
                self.frame_height = inferred_h
                
                # Calculate preview
                self.calculate_preview()
                
            except Exception as e:
                self.preview_label.setText(f"Error loading: {str(e)}")
    
    def browse_output(self):
        """Browse for output directory"""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder"
        )
        
        if directory:
            self.output_path = directory
            self.output_path_edit.setText(directory)
    
    def clear_cache(self):
        """Clear cached spritesheet"""
        if self.cached_spritesheet:
            try:
                self.cached_spritesheet.close()
            except:
                pass
        self.cached_spritesheet = None
        self.cached_path = None
    
    def load_spritesheet(self):
        """Load and cache the spritesheet"""
        if self.cached_path != self.spritesheet_path or self.cached_spritesheet is None:
            self.clear_cache()
            self.cached_spritesheet = Image.open(self.spritesheet_path)
            self.cached_path = self.spritesheet_path
        return self.cached_spritesheet
    
    def calculate_preview(self):
        """Calculate and display preview information"""
        if not self.spritesheet_path:
            self.preview_label.setText("No spritesheet loaded")
            return
        
        try:
            img = self.load_spritesheet()
            width, height = img.size
            
            frame_w = self.frame_width
            frame_h = self.frame_height
            
            frames_x = width // frame_w
            frames_y = height // frame_h
            total = frames_x * frames_y
            
            # Check for waste
            unused_width = width % frame_w
            unused_height = height % frame_h
            
            # Estimate disk space needed
            # PNG compression varies, but typically 2-4 bytes per pixel for RGBA
            # Using 3 bytes as average
            bytes_per_frame = frame_w * frame_h * 3
            estimated_total_mb = (bytes_per_frame * total) / (1024 * 1024)
            
            info = (
                f"Spritesheet: {width}×{height}px | "
                f"Frames: {frames_x}×{frames_y} grid | "
                f"Total: {total} frames\n"
                f"Estimated disk space: {estimated_total_mb:.2f} MB"
            )
            
            if unused_width > 0 or unused_height > 0:
                info += f"\n⚠ Warning: {unused_width}px width and {unused_height}px height will be unused"
            
            self.preview_label.setText(info)
            
        except Exception as e:
            self.preview_label.setText(f"Error: {str(e)}")
            self.clear_cache()
    
    def validate_output_path(self):
        """Validate that output path is writable"""
        output_dir = Path(self.output_path_edit.text())
        
        # Check if parent exists
        if not output_dir.parent.exists():
            return False, "Parent directory does not exist"
        
        # Try to create directory
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return False, f"Cannot create output directory: {str(e)}"
        
        # Check if writable
        if not os.access(output_dir, os.W_OK):
            return False, "Output directory is not writable"
        
        return True, ""
    
    def start_split(self):
        """Start the splitting process"""
        if not self.spritesheet_path:
            QMessageBox.critical(self, "Error", "Please select a spritesheet file")
            return
        
        if self.frame_width <= 0 or self.frame_height <= 0:
            QMessageBox.critical(self, "Error", "Frame dimensions must be positive")
            return
        
        # Validate output path
        valid, error_msg = self.validate_output_path()
        if not valid:
            QMessageBox.critical(self, "Error", f"Invalid output path:\n{error_msg}")
            return
        
        # Validate prefix
        prefix = self.prefix_edit.text().strip()
        if not prefix:
            QMessageBox.critical(self, "Error", "Filename prefix cannot be empty")
            return
        
        try:
            spritesheet = self.load_spritesheet()
            output_dir = Path(self.output_path_edit.text())
            start = self.start_index_spinbox.value()
            pad = self.padding_spinbox.value()
            
            # Create worker and thread
            self.worker_thread = QThread()
            self.worker = SplitterWorker(
                spritesheet, self.frame_width, self.frame_height,
                output_dir, prefix, start, pad
            )
            self.worker.moveToThread(self.worker_thread)
            
            # Connect signals
            self.worker_thread.started.connect(self.worker.run)
            self.worker.progress.connect(self.update_progress)
            self.worker.finished.connect(self.split_finished)
            self.worker.error.connect(self.split_error)
            
            # Cleanup on finish
            self.worker.finished.connect(self.worker_thread.quit)
            self.worker.error.connect(self.worker_thread.quit)
            self.worker_thread.finished.connect(self.cleanup_worker)
            
            # Update UI
            self.split_btn.setEnabled(False)
            self.status_label.setText("Processing...")
            self.status_label.setStyleSheet("color: orange;")
            self.progress_bar.setValue(0)
            
            # Start thread
            self.worker_thread.start()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start splitting:\n{str(e)}")
            self.cleanup_worker()
    
    def cleanup_worker(self):
        """Clean up worker and thread"""
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if self.worker_thread:
            self.worker_thread.deleteLater()
            self.worker_thread = None
    
    def update_progress(self, value):
        """Update progress bar"""
        self.progress_bar.setValue(value)
    
    def split_finished(self, count, output_dir):
        """Handle successful completion"""
        self.split_btn.setEnabled(True)
        self.status_label.setText(f"Success! Extracted {count} frames")
        self.status_label.setStyleSheet("color: #5d9cec;")
        self.progress_bar.setValue(100)
        QMessageBox.information(
            self, "Success",
            f"Successfully extracted {count} frames!\n\nSaved to:\n{output_dir}"
        )
    
    def split_error(self, error_msg):
        """Handle error"""
        self.split_btn.setEnabled(True)
        self.status_label.setText(f"Error: {error_msg}")
        self.status_label.setStyleSheet("color: red;")
        QMessageBox.critical(self, "Error", f"An error occurred:\n{error_msg}")
    
    def cleanup(self):
        """Cleanup resources"""
        # Stop worker if running
        if self.worker:
            self.worker.stop()
        
        # Wait for thread to finish
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.quit()
            self.worker_thread.wait(2000)
        
        # Clear cache
        self.clear_cache()
        
        # Reset UI
        self.progress_bar.setValue(0)


class SpriteToolkitApp(QMainWindow):
    """Main application window with tabbed interface"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sprite Toolkit - Animation & Spritesheet Tools")
        self.setMinimumSize(1100, 750)
        
        self.init_ui()
        self.apply_styles()
    
    def init_ui(self):
        """Initialize the UI"""
        central = QWidget()
        self.setCentralWidget(central)
        
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        
        # Add tabs
        self.coin_animator = CoinAnimatorTab()
        self.sheet_to_gif = SheetToGifTab()
        self.spritesheet_splitter = SpriteSheetSplitterTab()
        
        self.tabs.addTab(self.coin_animator, "🪙 Coin Animator")
        self.tabs.addTab(self.sheet_to_gif, "🎬 Sheet to GIF")
        self.tabs.addTab(self.spritesheet_splitter, "✂ Spritesheet Splitter")
        
        # Connect tab change to pause animations
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        layout.addWidget(self.tabs)
    
    def on_tab_changed(self, index):
        """Handle tab change - pause animations when not visible"""
        # Pause coin animator when switching away from it
        if index != 0:
            self.coin_animator.pause_on_hide()
        
        # Pause sheet to gif when switching away from it
        if index != 1:
            self.sheet_to_gif.pause_on_hide()
    
    def closeEvent(self, event):
        """Handle application close - cleanup resources"""
        # Stop coin animator
        self.coin_animator.cleanup()
        
        # Stop sheet to gif
        self.sheet_to_gif.cleanup()
        
        # Stop spritesheet splitter
        self.spritesheet_splitter.cleanup()
        
        event.accept()
    
    def apply_styles(self):
        """Apply global stylesheet"""
        self.setStyleSheet("""
            QMainWindow {
                background: #1a1a1a;
            }
            QWidget {
                background: #1a1a1a;
                color: #fff;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 12px;
            }
            QTabWidget::pane {
                border: 1px solid #3d3d3d;
                background: #1a1a1a;
            }
            QTabBar::tab {
                background: #2d2d2d;
                color: #aaa;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background: #1a1a1a;
                color: #fff;
                border-bottom: 2px solid #5d9cec;
            }
            QTabBar::tab:hover:!selected {
                background: #3d3d3d;
            }
            QPushButton {
                background: #3d3d3d;
                color: #fff;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #4d4d4d;
            }
            QPushButton:pressed {
                background: #5d5d5d;
            }
            QPushButton:disabled {
                background: #2d2d2d;
                color: #666;
            }
            QLabel {
                color: #ccc;
            }
            QGroupBox {
                color: #fff;
                font-weight: bold;
                border: 2px solid #3d3d3d;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit {
                background: #3d3d3d;
                color: #fff;
                border: 1px solid #5d5d5d;
                border-radius: 4px;
                padding: 6px;
            }
            QLineEdit:focus {
                border: 1px solid #5d9cec;
            }
            QLineEdit:read-only {
                background: #2d2d2d;
                color: #888;
            }
            QSpinBox, QDoubleSpinBox {
                background: #3d3d3d;
                color: #fff;
                border: 1px solid #5d5d5d;
                border-radius: 4px;
                padding: 5px;
            }
            QSpinBox:focus, QDoubleSpinBox:focus {
                border: 1px solid #5d9cec;
            }
            QSlider::groove:horizontal {
                background: #2d2d2d;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #5d9cec;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: #7db4f5;
            }
            QProgressBar {
                background: #2d2d2d;
                border: 1px solid #3d3d3d;
                border-radius: 4px;
                text-align: center;
                color: #fff;
            }
            QProgressBar::chunk {
                background: #5d9cec;
                border-radius: 3px;
            }
            QRadioButton {
                spacing: 5px;
            }
            QRadioButton::indicator {
                width: 15px;
                height: 15px;
                border-radius: 8px;
                border: 2px solid #5d5d5d;
                background: #2d2d2d;
            }
            QRadioButton::indicator:checked {
                background: #5d9cec;
                border: 2px solid #5d9cec;
            }
            QRadioButton::indicator:hover {
                border: 2px solid #7db4f5;
            }
        """)


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    
    # Set application metadata
    app.setApplicationName("Sprite Toolkit")
    app.setOrganizationName("SpriteTools")
    app.setApplicationVersion("2.0.0")
    
    # Create and show main window
    window = SpriteToolkitApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()