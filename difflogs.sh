rm -fr /src/logs/morph/*
cp /src/cache/artifacts/*-build-log /src/logs/morph

rm -fr /src/logs/ybd/*
cp /src/cache/ybd-artifacts/*build-log /src/logs/ybd

sed -i 's|src/staging/[^/]*/[^/]*|STAGING|g' /src/logs/ybd/*
sed -i 's|src/tmp/staging/[^/]*|STAGING|g' /src/logs/morph/*

diff /src/logs/morph/*.$1-build-log /src/logs/ybd/$1@* | less