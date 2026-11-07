# IX-Ray 1.3.6 Windows builds

The public workflow builds the pinned upstream source on standard Windows
GitHub-hosted runners and verifies the hash-locked export before compiling.
Release artifacts contain the tested x64 runtime and source manifests.
Matching symbols and Windows QA logs are available as separate artifacts.

The CoP condition replay runs the actual Lua code with simulated game effects.
Its timings describe that fixture. They do not measure the in-game spawn path.
