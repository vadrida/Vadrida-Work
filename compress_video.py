import os
import subprocess
from imageio_ffmpeg import get_ffmpeg_exe

input_file = r"static\videos\background 2.mp4"
output_file = r"static\videos\background_2_compressed.mp4"

if not os.path.exists(input_file):
    print(f"Error: Input file not found at {input_file}")
    exit(1)

ffmpeg_exe = get_ffmpeg_exe()

command = [
    ffmpeg_exe,
    "-y",
    "-i", input_file,
    "-vcodec", "libx264",
    "-crf", "30",
    "-preset", "fast",
    "-an",
    output_file
]

print("Compressing video... This might take a few seconds.")
result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

if result.returncode == 0:
    print(f"Success! Compressed video saved to {output_file}")
    print(f"Original size: {os.path.getsize(input_file) / 1024 / 1024:.2f} MB")
    print(f"Compressed size: {os.path.getsize(output_file) / 1024 / 1024:.2f} MB")
else:
    print("Compression failed.")
    print(result.stderr)
