# Spotify Control for StreamController

This WIP plugin allows you to control Spotify using StreamController. (Spotify Premium required)

It currently only provides actions for:

  * play/pause/resume
  * next song
  * previous song
  * switch shuffle mode
  * switch repeat mode
  * adjust volume in 10% steps
  * show cover-art in play/resume button

## Installation & Configuration

1.  Ensure you have StreamController installed.
2.  Copy the Extension to StreamControllers plugin folder (eg. `~/.var/app/com.core447.StreamController/data/plugins` for a flatpak installation)
3.  Create a Spotify App on https://developer.spotify.com/dashboard
   1. Set the Appname to whatever you want
   2. set the redirect URL to https://stream-controller/callback
   3. copy the clientID and client secret
4.  Configure the plugin with your Spotify Client ID and Client Secret within the StreamController settings and press "Login".
5.  Login to Spotify and accept the request for playback permissions
6.  Close the settings
7.  Use Actions on your Streamdeck


## TODO:

- more functions
- cleanup Code

## Asset Attributions

Images used in the `assets` folder are from fonts.google.com and licensed under the Apache License, Version 2.0. You can retrieve a copy of the license at [https://www.apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0).
