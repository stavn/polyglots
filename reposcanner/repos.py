import datetime
import os
from collections import Counter
from subprocess import check_output
import chardet
import requests

from . import db

GITHUB_CLIENT_ID = os.environ['GITHUB_CLIENT_ID']
GITHUB_CLIENT_SECRET = os.environ['GITHUB_CLIENT_SECRET']


class SparseList(list):
    def __init__(self, fill=int):
        super(SparseList, self).__init__()
        self._fill = fill
    def __setitem__(self, index, value):
        missing = index - len(self) + 1
        if missing > 0:
            self.extend([self._fill()] * missing)
        list.__setitem__(self, index, value)
    def __getitem__(self, index):
        try:
            return list.__getitem__(self, index)
        except IndexError:
            return self._fill()


def update_mongo_repo(repo, doc):
    """ update/insert (upsert) a repo record in mongo """
    repos = db.repos
    repos.update(
        {'user': repo.user,
         'name': repo.name,
         'language': repo.lang,
         'rank': repo.rank,
         },
        {'$set': doc},
        upsert=True)


def analyze_commits(repo):
    try:
        commits = repo.repo.revision_history(repo.repo.head())
    except:
        print("* Bad repo: {} {}".format(repo.lang, repo.identifier))
        return

    doc = {}
    doc[u'num_commits'] = len(commits)
    oldest = commits[-1]
    latest = commits[0]
    doc[u'oldest_commit'] = datetime.datetime.utcfromtimestamp(oldest.commit_time)
    doc[u'latest_commit'] = datetime.datetime.utcfromtimestamp(latest.commit_time)
    update_mongo_repo(repo, doc)
    return("{} commits".format(doc['num_commits']))


def count_committers(repo):
    try:
        commits = repo.repo.revision_history(repo.repo.head())
    except:
        return("Bad repo: {} {}".format(repo.lang, repo.identifier))

    counts = Counter()
    for author in [c.author for c in commits]:
        if type(author) != unicode:
            try:
                a = author.decode('utf-8')
            except UnicodeDecodeError:
                detected = chardet.detect(author)
                try:
                    a = author.decode(detected['encoding'])
                except:
                    print('Unable to decode author: {}'.format(author))
                    continue
        counts[a] += 1

    # not allowed to use periods in key names in mongodb!
    # break up authors into array of dicts
    doc = {
        u'authors_count': len(counts),
        u'authors': [{'name': k, 'commits': v} for k, v in counts.items()],
    }
    update_mongo_repo(repo, doc)
    return('{} distinct committers'.format(len(counts)))


def repo_size(repo):
    raw = check_output(["du", "-sb", repo.path])
    size = int(raw.split('\t')[0])
    update_mongo_repo(repo, {'disk_bytes': size})
    return('{} bytes'.format(size))


def commit_days_histogram(repo):
    try:
        commits = repo.repo.revision_history(repo.repo.head())
    except:
        return("Bad repo: {} {}".format(repo.lang, repo.identifier))

    # keep track of distribution of commits by day of week
    weekdays = Counter({u'0': 0, u'1': 0, u'2': 0, u'3': 0, u'4': 0, u'5': 0, u'6': 0})

    # histogram of number of daily commits
    oneday = datetime.timedelta(days=1)
    oldest = datetime.datetime.utcfromtimestamp(commits[-1].commit_time).date()
    latest = datetime.datetime.utcfromtimestamp(commits[0].commit_time).date()
    index = oldest
    dates = Counter()  # one for every day between oldest and latest
    histogram = Counter()

    while index <= latest:
        dates[index] = 0
        index += oneday

    for c in commits:
        ts = datetime.datetime.utcfromtimestamp(c.commit_time)
        date = ts.date()
        dates[date] += 1
        weekdays[unicode(date.weekday())] += 1

    for v in dates.values():
        histogram[unicode(v)] += 1

    doc = {
        'commit_days_of_week': dict(weekdays),
        'commit_histogram': dict(histogram)
    }
    update_mongo_repo(repo, doc)
    return('Done.')


def github_repo_metadata(repo):
    url_template = 'https://api.github.com/repos/{user}/{repo}?client_id={client_id}&client_secret={client_secret}'
    try:
        r = requests.get(
            url_template.format(
                user=repo.user, repo=repo.name,
                client_id=GITHUB_CLIENT_ID, client_secret=GITHUB_CLIENT_SECRET))
    except:
        return('Unable to fetch!')

    doc = {}
    properties = [
        u'has_wiki',
        u'description',
        u'network_count',
        u'watchers_count',
        u'size',
        u'homepage',
        u'fork',
        u'forks',
        u'has_issues',
        u'master_branch',
        u'has_downloads',
        u'watchers',
        u'forks_count',
        u'default_branch',
    ]
    data = r.json()
    for p in properties:
        if p in data:
            doc[p] = data[p]
    doc[u'organization'] = 'organization' in data
    remaining = r.headers['x-ratelimit-remaining']
    update_mongo_repo(repo, doc)
    return('Done ({} remaining)'.format(remaining))


def commit_message_heatmap(repo):
    try:
        commits = repo.repo.revision_history(repo.repo.head())
    except:
        return("Bad repo: {} {}".format(repo.lang, repo.identifier))

    rows = SparseList(fill=Counter)
    for commit in commits:
        try:
            u = commit.message.decode('utf-8')
        except UnicodeDecodeError:
            detected = chardet.detect(commit.message)
            try:
                u = commit.message.decode(detected['encoding'])
            except UnicodeDecodeError:
                print "*** Skipping commit (unknown encoding): {}".format(commit.sha)
                continue
        lines = [l.strip() for l in u.split(u'\n')]
        # remove blank trailing lines
        while True:
            if len(lines) > 0 and lines[-1] == u'':
                lines.pop()
            else:
                break

        for row, line in enumerate(lines):
            l = len(line)
            if l > 0:
                lengths = rows[row]
                lengths[l] += 1
                rows[row] = lengths

    sortedrows = []
    for row in rows:
        # row tuples are (length, frequency)
        # sort by descending line length
        sortedrows.append(sorted(row.items(), reverse=True, key=lambda x: x[0]))

    update_mongo_repo(repo, {u'commit_message_heatmap': sortedrows})
    return('{} lines'.format(len(rows)))
