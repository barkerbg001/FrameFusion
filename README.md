  <body>
    <h1>FrameFusion</h1>
    <p>This is a Python script that creates a video from a set of images and adds a random audio clip to each video.</p>
    <h2>Getting Started</h2>
    <p>To use this script, you'll need to have Python 3.x installed on your system along with the following libraries:</p>
    <ul>
      <li>cv2</li>
      <li>numpy</li>
      <li>glob</li>
      <li>random</li>
      <li>moviepy</li>
    </ul>
    <p>You can install these libraries using the following command:</p>
    <pre><code>pip install opencv-python numpy glob3 pydub random  moviepy</code></pre>
    <h2>Usage</h2>
    <ol>
      <li>Clone or download the script to your computer.</li>
      <li>Add your images to the "images" folder. The script reads all PNG files in each subfolder of the "images" folder and creates a video for each subfolder.</li>
      <li>Add your audio files to the "audio" folder. The script selects a random audio file from this folder and adds it to the video.</li>
      <li>Run the script using the following command:</li>
      <pre><code>python main.py</code></pre>
      <li>The script will create a video for each subfolder in the "images" folder and save it in the "output" folder.</li>
    </ol>
    <h2>Customization</h2>
    <ul>
      <li>If you want to add more image or audio files, simply add them to the "images" or "audio" folder, respectively.</li>
    </ul>
    <h2>License</h2>
    <p>This script is licensed under the MIT License. Feel free to modify and use it for your own projects.</p>
  </body>
