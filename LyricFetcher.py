"""
This script is used to fetch lyrics from Genius.com and write to metadata for a directory of mp3 files.

To use this script, you will need to do two things:
    1) obtain an access token for Genius' API, and put that information in the 'genius_api_config.py' file. See the file for more information.
    2) insert your directory location in the 'mp3_directory' variable at the bottom of this file.
"""

from genius_api_config import client_id, client_secret, client_access_token
from fuzzywuzzy import fuzz
from alive_progress import alive_bar
import requests
import pprint as pp
import html2text
import re
import eyed3
import os
import time

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# need this to avoid 'Lame tag CRC check failed' error
eyed3.log.setLevel("ERROR")

# API query URL
search_url = 'https://api.genius.com/search?q={}'

# HTTPS header data
headers = {'Authorization': 'Bearer ' + client_access_token,
        'User-Agent': 'CompuServe Classic/1.22',
        'Accept': 'application/json',
        'Host': 'api.genius.com',
        'response_type': 'code',
        'scope': 'me vote create_annotation manage_annotation'}

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def get_song_artist(audiofile) -> str:
    """
    Get song artist from audiofile.
    Args:
        audiofile (eyed3.mp3.Mp3AudioFile): Current mp3 file.
    Returns:
        str
    """
    artist = audiofile.tag.artist
    artist = re.sub('\/.+', '', artist)
    return artist


def get_song_title(audiofile) -> str:
    """
    Get song artist from audiofile.
    Args:
        audiofile (eyed3.mp3.Mp3AudioFile): Current mp3 file.
    Returns:
        str
    """

    title = audiofile.tag.title
    # this code removes hidden unicode char '\x00\ufeff'. If left in, messes with search query to Genius API
    if ('\\x00\\ufeff' in repr(title)):
        title = re.sub('\\x00\\ufeff.+', '', title)
    return title

def get_song_lyric_page(artist, song) -> str:
    """
    Get webpage for lyrics.
    Args:
        artist (str): song artist
        song (str): song title
    Returns:
        str
    """
    
    fullName = artist.replace(" ", "%20").strip() + "%20" + song.replace(" ", "%20").strip()
    
    try:
        response = requests.get(search_url.format(fullName), headers = headers)

        if response.json()['response']['hits']:

            # values of artist and title returned from top hit
            returned_artist = response.json()['response']['hits'][0]['result']['artist_names']
            returned_title = response.json()['response']['hits'][0]['result']['title']
            
            # string comparison of artist and title returned against what was queried
            fuzzRatioArtist = fuzz.ratio(str.lower(artist), str.lower(returned_artist))
            fuzzRatioTitle = fuzz.ratio(str.lower(song), str.lower(returned_title))
            
            # check if artist and song are close enough match to know we have right page
            if (((str.lower(artist) in str.lower(returned_artist)) or (fuzzRatioArtist >= 50)) and (fuzzRatioTitle >= 50)):
                url = response.json()['response']['hits'][0]['result']['url']
                return url

    except:
        return ''

def fetch_lyrics(lyrics_url) -> str:
    """
    Get lyrics from genius webpage.
    Args:
        artist (str): song artist
        song (str): song title
    Returns:
        str
    """

    page = requests.get(lyrics_url).text
    text = html2text.html2text(page)

    try:
        lyrics = re.search('(?:##[\w\W]*?Lyrics\s*([\w\W]*?Read\sMore)?[\s]*)([\w\W]*)(?:[\s][\d]*?Embed)', text).group(2)
        return lyrics
    except AttributeError:
        return ''

def clean_lyrics(lyrics):
    """
    This function does a variety of regex substitutions to clean up the lyrics returned from Genius.
    Args:
        lyrics (str): Raw lyrics from Genius webpage.
    Returns:
        str
    """

    # remove all square brackets which are used for notes
    lyrics = re.sub('\[|\]', '', lyrics)
    
    # remove unnecessary blank spaces at the end of each line / [^\S]+$ / [\s\n\t\r]+$ / \s\s$ (w multiline) WORKS
    lyrics = re.sub('[ ]+$', '', lyrics, flags = re.MULTILINE)
    lyrics = re.sub('^[ ]+', '', lyrics, flags = re.MULTILINE) # ^[^\n\w\d]+
    
    # first thing to strip is all the '(/123/blah-blah-blah)
    lyrics = re.sub('\(\/[\d]+?\/[\w\W]*?\)', '', lyrics)
    
    # remove unnecessary meta text
    lyrics = re.sub('\nSee [\w\W]* LiveGet [^\n]*\n[^\n]*\n', '', lyrics)
    lyrics = re.sub('\nYou might also like\n', '', lyrics)
    
    # remove italic, asterisk and slash symbols
    lyrics = re.sub('[_]+', '', lyrics)
    lyrics = re.sub('([*]+)', '', lyrics)
    lyrics = re.sub('\\-', '-', lyrics)
    
    # meta info
    lyrics = re.sub('^Produced by [^\n]*\n*', '', lyrics, flags = re.MULTILINE)
    lyrics = re.sub('^Video by [^\n]*\n*', '', lyrics, flags = re.MULTILINE)
    
    # various issues with apostrophes
    lyrics = re.sub("n 't", "n't", lyrics)
    lyrics = re.sub("e 's", "e's", lyrics)
    lyrics = re.sub("I 'm", "I'm", lyrics)
    lyrics = re.sub("t 's", "t's", lyrics)

    # put square brackets around parts of song e.g. intro, verse, chorus etc.
    lyrics = re.sub('^((Intro|Verse|Pre-[Cc]horus|Chorus|Post-[Cc]horus|Instrumental|Interlude|Hook|Bridge|Outro|Refrain|Guitar [Ss]olo|Bass [Ss]olo|Keyboard [Ss]olo|Saxophone [Ss]olo|Drum [Ss]olo|Flute [Ss]olo|Ad-lib|Break|Drop|Spoken)[^\n]*)', '[\g<0>]', lyrics, flags = re.MULTILINE)

    # remove spaces around brackets etc
    lyrics = re.sub('([\(\[])[ ]+', '\g<1>', lyrics)
    lyrics = re.sub('[ ]+([\)\],])', '\g<1>', lyrics)

    # strip leading and trailing whitespace
    lyrics = str.strip(lyrics)

    return lyrics


def write_lyrics_to_file(audiofile, lyrics):
    """
    Write fetched lyrics to audiofile lyrics metadata tag.
    Args:
        audiofile (eyed3.mp3.Mp3AudioFile): Current mp3 file.
        lyrics (str): The cleaned lyrics.
    """

    audiofile.tag.lyrics.set(lyrics)
    try:
        audiofile.tag.save()
    except:
        pass

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main(mp3_directory):
    startTime = time.time()

    rootDir = mp3_directory
    dirTree = os.walk(rootDir)

    for dirPaths, subPaths, files in dirTree:
        print('\nProcessing files in: ' + str(dirPaths))
        with alive_bar(len(files)) as progress_bar:
            for currentFile in files:

                progress_bar()

                if str(currentFile).lower().endswith('.mp3'):
                    audiofile = eyed3.load(rootDir + '\\' + currentFile)

                    # sometimes audiofile is 'NoneType' for some reason
                    if audiofile is None:
                        print(str(currentFile) + ' is NoneType')
                        continue

                    artist = get_song_artist(audiofile)
                    song = get_song_title(audiofile)

                    print(f'{artist} - {song}')

                    lyrics_url = get_song_lyric_page(artist, song)

                    if lyrics_url != None:
                        lyrics = fetch_lyrics(lyrics_url)
                        lyrics = clean_lyrics(lyrics)
                        write_lyrics_to_file(audiofile, lyrics)
                    else:
                        continue
                                                            
                else:
                    print(str(currentFile) + ' is not mp3')
                    continue   

    finishTime = time.time()
    executionTime = (finishTime - startTime)
    print('Time to run (s): ' + str(executionTime))


if __name__ == "__main__":
    mp3_directory = r'C:\Users\Odhran\Programming\LyricFetcher'

    main(mp3_directory)