from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import random
import math
import imageio
import numpy as np
from io import BytesIO
from datetime import datetime

class PremiumCardGenerator:
    def __init__(self, output_dir="cards"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
    def generate_card_image(self, card_id, numbers, called_numbers=None, 
                           player_name="Player", highlight_cells=None,
                           is_winner=False, frame=0):
        """Generate a single frame of a premium Bingo card"""
        
        if called_numbers is None:
            called_numbers = []
        if highlight_cells is None:
            highlight_cells = []
            
        # Premium dimensions
        cell_size = 75
        padding = 12
        header_height = 60
        card_width = cell_size * 5 + padding * 6
        card_height = card_width + header_height + 70
        
        # Create base with gradient background
        img = Image.new('RGB', (card_width, card_height), '#0a0a1a')
        draw = ImageDraw.Draw(img)
        
        # Draw premium gradient background
        for y in range(card_height):
            color_value = int(20 + (y / card_height) * 30)
            color = (color_value, color_value, color_value + 20)
            draw.rectangle([0, y, card_width, y+1], fill=color)
        
        # Load fonts
        try:
            header_font = ImageFont.truetype("arial.ttf", 34)
            number_font = ImageFont.truetype("arial.ttf", 28)
            footer_font = ImageFont.truetype("arial.ttf", 18)
            large_font = ImageFont.truetype("arial.ttf", 40)
        except:
            header_font = ImageFont.load_default()
            number_font = ImageFont.load_default()
            footer_font = ImageFont.load_default()
            large_font = ImageFont.load_default()
        
        # Draw decorative border
        border_width = 3
        draw.rectangle([0, 0, card_width-1, card_height-1], 
                      outline='#2a2a5a', width=border_width)
        
        # Draw BINGO header with gradient colors and glow
        header_colors = ['#ff6b6b', '#ffd93d', '#6bcb77', '#4d96ff', '#ff6bff']
        letters = ['B', 'I', 'N', 'G', 'O']
        
        for i, (letter, color) in enumerate(zip(letters, header_colors)):
            x = padding + i * (cell_size + padding) + cell_size // 2
            
            # Glow effect
            for offset in range(-3, 4):
                glow_alpha = 100 - abs(offset) * 20
                glow_color = f'#{hex(int(glow_alpha))[2:].zfill(2)}ffff'
                draw.text((x - 18 + offset, padding + 5 + offset), 
                         letter, fill='#222', font=large_font)
            
            # Main text
            draw.text((x - 18, padding + 5), letter, fill=color, font=large_font)
        
        # Draw cells
        for row in range(5):
            for col in range(5):
                # Cell position
                x1 = padding + col * (cell_size + padding)
                y1 = padding + header_height + row * (cell_size + padding)
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                
                # Get number
                if row == 2 and col == 2:
                    value = "★"
                    is_free = True
                else:
                    letter = letters[col]
                    val = numbers[letter][row]
                    value = str(val)
                    is_free = False
                
                # Check if called or winning
                is_called = value in called_numbers and not is_free
                is_winning = (row, col) in highlight_cells
                is_winner_cell = is_winning and is_winner
                
                # Cell styling
                if is_free:
                    bg_color = '#2a2a4a'
                    border_color = '#ffd700'
                    text_color = '#ffd700'
                    glow_color = '#ffd700'
                elif is_winner_cell:
                    # Pulsing gold for winner cells
                    pulse = int(150 + 105 * abs(math.sin(frame * 0.2)))
                    bg_color = f'#3a2a0a'
                    border_color = f'#{hex(pulse)[2:].zfill(2)}d700'
                    text_color = '#ffd700'
                    glow_color = '#ffd700'
                elif is_called:
                    bg_color = '#1a1a2a'
                    border_color = '#4a4a6a'
                    text_color = '#666'
                    glow_color = None
                else:
                    bg_color = '#1a1a2e'
                    border_color = '#3a3a5a'
                    text_color = '#ffffff'
                    glow_color = None
                
                # Draw cell
                draw.rectangle([x1, y1, x2, y2], fill=bg_color, 
                              outline=border_color, width=2)
                
                # Glow effect for special cells (solid RGB — Pillow has no rgba() strings)
                if is_winner_cell or is_free:
                    glow_colors = [(80, 62, 10), (160, 128, 22), (230, 195, 40)]
                    for r, glow_color in zip(range(3, 0, -1), glow_colors):
                        draw.rectangle([x1-r, y1-r, x2+r, y2+r],
                                       outline=glow_color, width=1)
                
                # Center text
                bbox = draw.textbbox((0, 0), value, font=number_font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                text_x = x1 + (cell_size - text_width) // 2
                text_y = y1 + (cell_size - text_height) // 2
                
                # Draw text
                draw.text((text_x, text_y), value, fill=text_color, font=number_font)
                
                # Mark called with X
                if is_called and not is_free:
                    draw.text((text_x + 25, text_y - 5), "✕", 
                             fill='#ff6b6b', font=number_font)
        
        # Add footer with player info and progress
        progress = len(called_numbers)
        status_text = f"🎯 {player_name}"
        card_text = f"Card #{card_id}"
        progress_text = f"📊 {progress}/75"
        
        footer_y = card_height - 55
        draw.text((padding, footer_y), status_text, fill='#888', font=footer_font)
        draw.text((card_width // 2 - 40, footer_y), card_text, fill='#666', font=footer_font)
        draw.text((card_width - padding - 80, footer_y), progress_text, fill='#888', font=footer_font)
        
        # Add progress bar
        bar_y = card_height - 25
        bar_height = 8
        progress_width = int((card_width - 40) * (progress / 75))
        
        # Background bar
        draw.rectangle([20, bar_y, card_width - 20, bar_y + bar_height], 
                      fill='#1a1a2e', outline='#3a3a5a', width=1)
        
        # Progress fill with gradient
        if progress > 0:
            for x in range(20, 20 + progress_width):
                progress_color = int(255 * (x - 20) / (card_width - 40))
                draw.rectangle([x, bar_y, x+1, bar_y + bar_height], 
                             fill=f'#{hex(255-progress_color)[2:].zfill(2)}{hex(255)[2:].zfill(2)}{hex(128)[2:].zfill(2)}')
        
        # Draw percentage
        percent = int((progress / 75) * 100)
        draw.text((card_width // 2 - 20, bar_y - 20), f"{percent}%", 
                 fill='#4a4a6a', font=footer_font)
        
        return img
    
    def generate_animated_card(self, card_id, numbers, called_numbers=None,
                              player_name="Player", highlight_cells=None,
                              is_winner=False):
        """Generate animated GIF card with effects"""
        
        if called_numbers is None:
            called_numbers = []
        if highlight_cells is None:
            highlight_cells = []
            
        frames = []
        num_frames = 20 if is_winner else 10
        
        for frame in range(num_frames):
            img = self.generate_card_image(
                card_id, numbers, called_numbers, player_name,
                highlight_cells, is_winner, frame
            )
            frames.append(img)
        
        # Save as animated GIF
        gif_path = os.path.join(self.output_dir, f"card_{card_id}_animated.gif")
        imageio.mimsave(gif_path, frames, duration=0.15, loop=0)
        return gif_path
    
    def generate_winning_celebration(self, card_id, numbers, called_numbers,
                                     player_name="Player", highlight_cells=None):
        """Generate winning celebration with confetti animation"""
        
        if highlight_cells is None:
            highlight_cells = []
            
        frames = []
        num_frames = 30
        
        for frame in range(num_frames):
            img = self.generate_card_image(
                card_id, numbers, called_numbers, player_name,
                highlight_cells, is_winner=True, frame=frame
            )
            
            # Add confetti
            img = self.add_confetti(img, frame)
            frames.append(img)
        
        # Save as animated GIF
        gif_path = os.path.join(self.output_dir, f"winner_{card_id}_celebration.gif")
        imageio.mimsave(gif_path, frames, duration=0.1, loop=0)
        return gif_path
    
    def add_confetti(self, img, frame):
        """Add confetti particles to image"""
        draw = ImageDraw.Draw(img)
        colors = ['#ff6b6b', '#ffd93d', '#6bcb77', '#4d96ff', '#ff6bff', '#ff8a5c']
        
        seed = frame * 100
        random.seed(seed)
        
        for i in range(30):
            x = (random.randint(0, img.width) + frame * 5) % img.width
            y = (random.randint(0, img.height) + frame * 3) % img.height
            color = random.choice(colors)
            size = random.randint(4, 10)
            shape = random.choice(['rect', 'circle'])
            
            if shape == 'rect':
                draw.rectangle([x, y, x+size, y+size], fill=color)
            else:
                draw.ellipse([x, y, x+size, y+size], fill=color)
        
        return img