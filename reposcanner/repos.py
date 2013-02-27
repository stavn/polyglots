import datetime
from collections import Counter
from subprocess import check_output

from . import db

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
    print("{} commits".format(doc['num_commits']))


def count_committers(repo):
    try:
        commits = repo.repo.revision_history(repo.repo.head())
    except:
        print("* Bad repo: {} {}".format(repo.lang, repo.identifier))
        return

    authors = [c.author for c in commits]
    counts = Counter()
    for a in authors:
        counts[a] += 1
    doc = {
        u'authors_count': len(counts.keys()),
        u'authors': counts,
    }
    update_mongo_repo(repo, doc)


def repo_size(repo):
    raw = check_output(["du", "-sb", repo.path])
    size = int(raw.split('\t')[0])
    print('{} size: {}'.format(repo, size))
    update_mongo_repo(repo, {'disk_bytes': size})
