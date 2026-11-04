#!/bin/bash
# Split a repository into batches to avoid pack size limits on git push

REMOTE=origin
BRANCH=$(git rev-parse --abbrev-ref HEAD)
BATCH_SIZE=500  # Adjust this smaller if you still hit size errors

# Check if the branch exists on the remote
if git show-ref --quiet --verify refs/remotes/$REMOTE/$BRANCH; then
    # If it exists, only push commits that aren't on the remote yet
    range=$REMOTE/$BRANCH..HEAD
else
    # Otherwise, push all commits from the beginning
    range=HEAD
fi

# Count the number of commits to push
n=$(git log --first-parent --format=format:x $range | wc -l)

# Push each batch starting from the oldest
for i in $(seq $n -$BATCH_SIZE 1); do
    h=$(git log --first-parent --reverse --format=format:%H --skip $i -n1)
    echo "Pushing commit batch at $h..."
    git push $REMOTE $h:refs/heads/$BRANCH
done

# Final push to ensure everything matches exactly
git push $REMOTE $BRANCH
