the function of this toolbox is to help manual annotation of social behavior
input:
1. video
2. corresponding timestamp file
3. behavior annotation table saved as csv/xlsx (if none, generate a new empty file)
    (example file:/Users/pany2/Janelia/RatCity/cohort7/fighting_notes.xlsx)
output:
updated behavior annotation table

key functions or modules
1. video loading, navigation. if the online navigation of video is slow, consider extracting each frame of video and saved in workspace/video_id/frames folder
2. timestamps parsing of timestamp file (either .npy or .json), and save correctly in the annotation table in different format (both datetime format and unix time format)
3. parsing annotation table to show in gui and save annotation in gui to the table

GUI
three panels:
1. top left, main panels showing the video frame, add a status bar above it showing corresponding time (datetime and timestamp) of current frame
2. top right, a vertically organized items including
   1) zoomin view of a subregion of the frame (centered where user click with a user defined zoomin factor)
   2) buttons: 'set event start time', 'set event end time' with read-only text field showing time 
   3) pull-down menu ‘event type'
   4) elements organized as a table with following columns
      1. 'name': name of each animal, each one should have different color background, consistent with the color used for annotation in main panel or zoomin view
      2. 'initiator': checkbox, once checked, require to click the center of the animal on a video frame (or zoomin view)
      3. 'victim': checkbox, once checked, require to click the center of the animal on a video frame (or zoomin view)
      4. 'intervenor': checkbox, once checked, require to click the center of the animal on a video frame (or zoomin view)
      5. 'observer': checkbox, once checked, require to click the center of the animal on a video frame (or zoomin view)
      6. 'winner': checkbox, can only choose from rows whose 'initiator' or 'victim' are checked, once checked, require to click the center of the animal on a video frame (or zoomin view)
      7. 'loser': checkbox, can only choose from rows whose 'initiator' or 'victim' are checked, once checked, require to click the center of the animal on a video frame (or zoomin view)
   5) text box 'other notes'
   6) button: 'submit new event', after click, check necessary fields
      1. start time
      2. event type
      3. initiator, one animal should be selected
3. bottom, video navigator and status organized into rows, from top to bottom, they are
   1. video navigator, with 
      1. a sliding bar to drag  
      2. a input text box to type exact frame number or time (datetime)
      3. buttons 'next event', 'previous event' to jump to start frame of the next/previous event, and also show corresponding information at top right panel
   2. visualization of ethogram, similar to this implementation: /Users/pany2/PycharmProjects/rat_city_master/ratcity_behavior/utils/ethogram_viewer.py

code style
1. keep code modular and organize files in the project well
2. add a README file, including guidance of installation, launch etc. 
3. a manual file describing the functionality of each component of GUI