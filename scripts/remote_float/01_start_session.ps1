[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SshHost,

    [int]$SshPort = 22,
    [string]$SshUser = "root",
    [string]$RemoteWorkerRoot = "/workspace/virtual-teacher-worker",
    [int]$LocalTunnelPort = 18011,
    [int]$RemoteWorkerPort = 8011
)

$ErrorActionPreference = "Stop"

if ($RemoteWorkerRoot -notmatch '^/[A-Za-z0-9._/-]+$') {
    throw "RemoteWorkerRoot contains unsupported shell characters."
}

$target = "${SshUser}@${SshHost}"
$forward = "${LocalTunnelPort}:127.0.0.1:${RemoteWorkerPort}"
$remoteCommand = "cd '${RemoteWorkerRoot}' && bash start_worker.sh && echo 'Remote FLOAT Worker started; keep this window open for the SSH tunnel.' && while true; do sleep 3600; done"
$sshArguments = @(
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-L", $forward,
    "-p", $SshPort.ToString(),
    $target,
    $remoteCommand
)

Write-Host "Starting the remote Worker and local tunnel..."
Write-Host "Local health URL: http://127.0.0.1:${LocalTunnelPort}/health"
Write-Host "Keep this window open. Closing it only stops the tunnel; Screen keeps the remote Worker running."

& ssh @sshArguments
if ($LASTEXITCODE -ne 0) {
    throw "SSH session exited with code $LASTEXITCODE."
}
