#!/bin/bash
# Reset demo state for Beacon

echo "🧹 Flushing Redis..."
docker exec -it weavehacks-redis redis-cli FLUSHALL

echo "🔄 Resetting Joplin fork to upstream..."
cd ~/code/joplin
git checkout dev
git fetch upstream
git reset --hard upstream/dev
git push -f origin dev

# Delete any beacon branches
git branch -r | grep 'beacon/' | sed 's/origin\///' | xargs -I {} git push origin --delete {} 2>/dev/null || true

echo "✅ Ready for next demo!"