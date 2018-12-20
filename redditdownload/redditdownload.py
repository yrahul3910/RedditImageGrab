#!/usr/bin/env python2
"""Download images from a reddit.com subreddit."""

from __future__ import print_function

import os
import re
import StringIO
import sys
import logging
from urllib2 import urlopen, HTTPError, URLError
from httplib import InvalidURL
from argparse import ArgumentParser
from os.path import (
    exists as pathexists, join as pathjoin, basename as pathbasename,
    splitext as pathsplitext)
from os import mkdir, getcwd
import time

from .gfycat import gfycat
from .reddit import getitems
from .deviantart import process_deviant_url


_log = logging.getLogger('redditdownload')


def request(url, *ar, **kwa):
    _retries = kwa.pop('_retries', 4)
    _retry_pause = kwa.pop('_retry_pause', 0)
    res = None
    for _try in xrange(_retries):
        try:
            res = urlopen(url, *ar, **kwa)
        except Exception as exc:
            if _try == _retries - 1:
                raise
            print("Try %r err %r  (%r)" % (
                _try, exc, url))
        else:
            break
    return res


# '.wrong_type_pages.jsl'
_WRONGDATA_LOGFILE = os.environ.get('WRONGDATA_LOGFILE')


def _log_wrongtype(_logfile=_WRONGDATA_LOGFILE, **kwa):
    if not _logfile:
        return
    import json
    data = json.dumps(kwa) + "\n"
    with open(_logfile, 'a', 1) as f:
        f.write(data)


class WrongFileTypeException(Exception):
    """Exception raised when incorrect content-type discovered"""


class FileExistsException(Exception):
    """Exception raised when file exists in specified directory"""


def extract_imgur_album_urls(album_url):
    """
    Given an imgur album URL, attempt to extract the images within that
    album

    Returns:
        List of qualified imgur URLs
    """
    response = request(album_url)
    info = response.info()

    # Rudimentary check to ensure the URL actually specifies an HTML file
    if 'content-type' in info and not info['content-type'].startswith('text/html'):
        return []

    filedata = response.read()
    # TODO: stop parsing HTML with regexes.
    match = re.compile(r'\"hash\":\"(.[^\"]*)\",\"title\"')
    items = []

    memfile = StringIO.StringIO(filedata)

    for line in memfile.readlines():
        results = re.findall(match, line)
        if not results:
            continue

        items += results

    memfile.close()
    # TODO : url may contain gif image.
    urls = ['http://i.imgur.com/%s.jpg' % (imghash) for imghash in items]

    return urls


def download_from_url(url, dest_file):
    """
    Attempt to download file specified by url to 'dest_file'

    Raises:

        WrongFileTypeException

            when content-type is not in the supported types or cannot
            be derived from the URL

        FileExceptionsException

            If the filename (derived from the URL) already exists in
            the destination directory.

        HTTPError

            ...
    """
    # Don't download files multiple times!
    if pathexists(dest_file):
        raise FileExistsException('URL [%s] already downloaded.' % url)

    response = request(url)
    info = response.info()
    actual_url = response.url
    if actual_url == 'http://i.imgur.com/removed.png':
        raise HTTPError(actual_url, 404, "Imgur suggests the image was removed", None, None)

    # Work out file type either from the response or the url.
    if 'content-type' in info.keys():
        filetype = info['content-type']
    elif url.endswith('.jpg') or url.endswith('.jpeg'):
        filetype = 'image/jpeg'
    elif url.endswith('.png'):
        filetype = 'image/png'
    elif url.endswith('.gif'):
        filetype = 'image/gif'
    elif url.endswith('.mp4'):
        filetype = 'video/mp4'
    elif url.endswith('.webm'):
        filetype = 'video/webm'
    else:
        filetype = 'unknown'

    # Only try to download acceptable image types
    if filetype not in ['image/jpeg', 'image/png', 'image/gif', 'video/webm', 'video/mp4']:
        raise WrongFileTypeException('WRONG FILE TYPE: %s has type: %s!' % (url, filetype))

    filedata = response.read()
    filehandle = open(dest_file, 'wb')
    filehandle.write(filedata)
    filehandle.close()


def process_imgur_url(url):
    """
    Given an imgur URL, determine if it's a direct link to an image or an
    album.  If the latter, attempt to determine all images within the album

    Returns:
        list of imgur URLs
    """
    if 'imgur.com/a/' in url or 'imgur.com/gallery/' in url:
        return extract_imgur_album_urls(url)

    # use beautifulsoup4 to find real link
    # find vid url only
    try:
        from bs4 import BeautifulSoup
        html = urlopen(url).read()
        soup = BeautifulSoup(html, 'lxml')
        vid = soup.find('div', {'class': 'video-container'})
        vid_type = 'video/webm'  # or 'video/mp4'
        vid_url = vid.find('source', {'type': vid_type}).get('src')
        if vid_url.startswith('//'):
            vid_url = 'http:' + vid_url
        return vid_url

    except Exception:
        # do nothing for awhile
        pass
    # Change .png to .jpg for imgur urls.
    if url.endswith('.png'):
        url = url.replace('.png', '.jpg')
    else:
        # Extract the file extension
        ext = pathsplitext(pathbasename(url))[1]
        if ext == '.gifv':
            url = url.replace('.gifv', '.gif')
        if not ext:
            # Append a default
            url += '.jpg'
    return [url]


def extract_urls(url):
    """
    Given an URL checks to see if its an imgur.com URL, handles imgur hosted
    images if present as single image or image album.

    Returns:
        list of image urls.
    """
    urls = []

    if 'imgur.com' in url:
        urls = process_imgur_url(url)
    elif 'deviantart.com' in url:
        urls = process_deviant_url(url)
    elif 'gfycat.com' in url:
        # choose the smallest file on gfycat
        gfycat_json = gfycat().more(url.split("gfycat.com/")[-1]).json()
        if gfycat_json["mp4Size"] < gfycat_json["webmSize"]:
            urls = [gfycat_json["mp4Url"]]
        else:
            urls = [gfycat_json["webmUrl"]]
    else:
        urls = [url]

    return urls


def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    # taken from http://stackoverflow.com/a/295466
    # with some modification
    import unicodedata
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = unicode(re.sub(r'[^\w\s-]', '', value).strip())
    # value = re.sub(r'[-\s]+', '-', value) # not replacing space with hypen
    return value


def parse_args(args):
    PARSER = ArgumentParser(description='Downloads files with specified extension'
                            'from the specified subreddit.')
    PARSER.add_argument('reddit', metavar='<subreddit>', help='Subreddit name.')
    PARSER.add_argument('dir', metavar='<dest_file>', nargs='?',
                        default=getcwd(), help='Dir to put downloaded files in.')
    PARSER.add_argument('--multireddit', default=False, action='store_true',
                        required=False,
                        help='Take multirredit instead of subreddit as input.'
                        'If so, provide /user/m/multireddit-name as argument')
    PARSER.add_argument('--last', metavar='l', default='', required=False,
                        help='ID of the last downloaded file.')
    PARSER.add_argument('--score', metavar='s', default=0, type=int, required=False,
                        help='Minimum score of images to download.')
    PARSER.add_argument('--num', metavar='n', default=1000, type=int, required=False,
                        help='Number of images to download. Set to 0 to disable the limit')
    PARSER.add_argument('--update', default=False, action='store_true', required=False,
                        help='Run until you encounter a file already downloaded.')
    PARSER.add_argument('--sfw', default=False, action='store_true', required=False,
                        help='Download safe for work images only.')
    PARSER.add_argument('--nsfw', default=False, action='store_true', required=False,
                        help='Download NSFW images only.')
    PARSER.add_argument('--filename-format', default='reddit', required=False,
                        help='Specify filename format: reddit (default), title or url')
    PARSER.add_argument('--title-contain', metavar='TEXT', required=False,
                        help='Download only if title contain text (case insensitive)')
    PARSER.add_argument('--regex', default=None, action='store', required=False,
                        help='Use Python regex to filter based on title.')
    PARSER.add_argument('--verbose', default=False, action='store_true',
                        required=False, help='Enable verbose output.')
    PARSER.add_argument('--skipAlbums', default=False, action='store_true',
                        required=False, help='Skip all albums')
    PARSER.add_argument('--mirror-gfycat', default=False, action='store_true', required=False,
                        help='Download available mirror in gfycat.com.')
    PARSER.add_argument('--sort-type', default=None, help='Sort the subreddit.')

    # TODO fix if regex, title contain activated

    parsed_argument = PARSER.parse_args(args)

    if parsed_argument.sfw is True and parsed_argument.nsfw is True:
        # negate both argument if both argument exist
        parsed_argument.sfw = parsed_argument.nsfw = False

    return parsed_argument


def parse_reddit_argument(reddit_args):
    if '+' not in reddit_args:
        return 'Downloading images from "%s" subreddit' % (reddit_args)
    elif len('Downloading images from "%s" subreddit' % (reddit_args)) > 80:
        # other print format if the line is more than 80 chars
        return 'Downloading images from subreddits:\n{}'.format('\n'.join(reddit_args.split('+')))
    else:
        # print in one line but with nicer format
        return 'Downloading images from "{}" subreddit'.format(', '.join(reddit_args.split('+')))


def main():
    ARGS = parse_args(sys.argv[1:])

    logging.basicConfig(level=logging.INFO)
    print(parse_reddit_argument(ARGS.reddit))

    TOTAL = DOWNLOADED = ERRORS = SKIPPED = FAILED = 0
    FINISHED = False

    # Create the specified directory if it doesn't already exist.
    if not pathexists(ARGS.dir):
        mkdir(ARGS.dir)

    # If a regex has been specified, compile the rule (once)
    RE_RULE = None
    if ARGS.regex:
        RE_RULE = re.compile(ARGS.regex)

    # compile reddit comment url to check if url is one of them
    reddit_comment_regex = re.compile(r'.*reddit\.com\/r\/(.*?)\/comments')

    LAST = ARGS.last

    start_time = None
    ITEM = None

    sort_type = ARGS.sort_type
    if sort_type:
        sort_type = sort_type.lower()

    # Image count to prepend to filename
    image_count = 1
    while not FINISHED:
        ITEMS = getitems(
            ARGS.reddit, multireddit=ARGS.multireddit, previd=LAST,
            reddit_sort=sort_type)

        # measure time and set the program to wait 4 second between request
        # as per reddit api guidelines
        end_time = time.clock()

        if start_time is not None:
            elapsed_time = end_time - start_time

            if elapsed_time <= 4:  # throttling
                time.sleep(4 - elapsed_time)

        start_time = time.clock()

        if not ITEMS:
            # No more items to process
            break

        for ITEM in ITEMS:
            TOTAL += 1

            # not downloading if url is reddit comment
            if ('reddit.com/r/' + ARGS.reddit + '/comments/' in ITEM['url'] or
                    re.match(reddit_comment_regex, ITEM['url']) is not None):
                print('    Skip:[{}]'.format(ITEM['url']))
                continue

            if ITEM['score'] < ARGS.score:
                if ARGS.verbose:
                    print('    SCORE: {} has score of {}'.format(ITEM['id'], ITEM['score']),
                          'which is lower than required score of {}.'.format(ARGS.score))

                SKIPPED += 1
                continue
            elif ARGS.sfw and ITEM['over_18']:
                if ARGS.verbose:
                    print('    NSFW: %s is marked as NSFW.' % (ITEM['id']))

                SKIPPED += 1
                continue
            elif ARGS.nsfw and not ITEM['over_18']:
                if ARGS.verbose:
                    print('    Not NSFW, skipping %s' % (ITEM['id']))

                SKIPPED += 1
                continue
            elif ARGS.regex and not re.match(RE_RULE, ITEM['title']):
                if ARGS.verbose:
                    print('    Regex not matched')

                SKIPPED += 1
                continue
            elif ARGS.skipAlbums and 'imgur.com/a/' in ITEM['url']:
                if ARGS.verbose:
                    print('    Album found, skipping %s' % (ITEM['id']))

                SKIPPED += 1
                continue

            if ARGS.title_contain and ARGS.title_contain.lower() not in ITEM['title'].lower():
                if ARGS.verbose:
                    print('    Title does not contain "{}",'.format(ARGS.title_contain),
                          'skipping {}'.format(ITEM['id']))

                SKIPPED += 1
                continue

            FILECOUNT = 0
            try:
                URLS = extract_urls(ITEM['url'])
            except Exception:
                _log.exception("Failed to extract urls for %r", URLS)
                continue
            for URL in URLS:
                try:
                    # Find gfycat if requested
                    if URL.endswith('gif') and ARGS.mirror_gfycat:
                        check = gfycat().check(URL)
                        if check.get("urlKnown"):
                            URL = check.get('webmUrl')

                    FILEEXT = pathsplitext(URL)[1]
                    # Trim any http query off end of file extension.
                    FILEEXT = re.sub(r'\?.*$', '', FILEEXT)
                    if not FILEEXT:
                        # A more usable option that empty.
                        # The extension can be fixed after downloading, but then the 'already downloaded' check will be harder.
                        FILEEXT = '.jpg'

                    # Only append numbers if more than one file
                    FILENUM = ('_%d' % FILECOUNT if len(URLS) > 1 else '')

                    # create filename based on given input from user
                    if ARGS.filename_format == 'url':
                        FILENAME = '%05d - %s%s%s' % (image_count, pathsplitext(pathbasename(URL))[0], '', FILEEXT)
                    elif ARGS.filename_format == 'title':
                        FILENAME = '%05d - %s%s%s' % (image_count, slugify(ITEM['title']), FILENUM, FILEEXT)
                        if len(FILENAME) >= 256:
                            shortened_item_title = slugify(ITEM['title'])[:256-len(FILENAME)]
                            FILENAME = '%05d - %s%s%s' % (image_count, shortened_item_title, FILENUM, FILEEXT)
                    else:
                        FILENAME = '%05d - %s%s%s' % (image_count, ITEM['id'], FILENUM, FILEEXT)
                    
                    image_count += 1  # Increment the image count
                    # join file with directory
                    FILEPATH = pathjoin(ARGS.dir, FILENAME)

                    # Improve debuggability list URL before download too.
                    # url may be wrong so skip that
                    if URL.encode('utf-8') == 'http://':
                        raise URLError('Url is empty')
                    else:
                        text_templ = '    Attempting to download URL[{}] as [{}].'
                        print(text_templ.format(URL.encode('utf-8'), FILENAME.encode('utf-8')))

                    # Download the image
                    try:
                        download_from_url(URL, FILEPATH)
                        # Image downloaded successfully!
                        print('    Sucessfully downloaded URL [%s] as [%s].' % (URL, FILENAME))
                        DOWNLOADED += 1
                        FILECOUNT += 1

                    except Exception as exc:
                        print('    %s' % (exc,))
                        ERRORS += 1

                    if ARGS.num and DOWNLOADED >= ARGS.num:
                        FINISHED = True
                        break
                except WrongFileTypeException as ERROR:
                    print('    %s' % (ERROR,))
                    _log_wrongtype(url=URL, target_dir=ARGS.dir,
                                   filecount=FILECOUNT, _downloaded=DOWNLOADED,
                                   filename=FILENAME)
                    SKIPPED += 1
                except FileExistsException as ERROR:
                    print('    %s' % (ERROR,))
                    ERRORS += 1
                    if ARGS.update:
                        print('    Update complete, exiting.')
                        FINISHED = True
                        break
                except HTTPError as ERROR:
                    print('    HTTP ERROR: Code %s for %s.' % (ERROR.code, URL))
                    FAILED += 1
                except URLError as ERROR:
                    print('    URL ERROR: %s!' % (URL,))
                    FAILED += 1
                except InvalidURL as ERROR:
                    print('    Invalid URL: %s!' % (URL,))
                    FAILED += 1
                except Exception as exc:
                    _log.exception("Problem with %r: %r", URL, exc)
                    FAILED += 1

            if FINISHED:
                break

        LAST = ITEM['id'] if ITEM is not None else None

    print('Downloaded {} files'.format(DOWNLOADED),
          '(Processed {}, Skipped {}, Exists {})'.format(TOTAL, SKIPPED, ERRORS))


if __name__ == "__main__":
    main()
