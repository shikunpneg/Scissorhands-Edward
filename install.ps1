# 把剪刀手 skill 装到 DSH 的 skill 根目录。
#   pwsh -File install.ps1                    装到 ~/.dsh/skills（全部会话可用）
#   pwsh -File install.ps1 -Scope Project     装到 <项目>/.dsh/skills
# 安装前会校验 frontmatter 并跑一遍测试。

[CmdletBinding()]
param(
    [ValidateSet("User", "Project")]
    [string]$Scope = "User",
    [string]$ProjectRoot = (Get-Location).Path,
    [switch]$Force,
    [switch]$SkipTest
)

$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
$SkillsSrc = Join-Path $RepoRoot "skills"
if (-not (Test-Path $SkillsSrc)) { throw "找不到 skills 目录：$SkillsSrc" }

$DestRoot = if ($Scope -eq "User") {
    Join-Path $env:USERPROFILE ".dsh\skills"
} else {
    Join-Path $ProjectRoot ".dsh\skills"
}

$skills = Get-ChildItem $SkillsSrc -Directory | Sort-Object Name
if ($skills.Count -eq 0) { throw "skills 目录为空：$SkillsSrc" }

# 1. 校验 frontmatter：缺 name / description 的 skill 会被 DSH 静默丢弃，必须提前拦住
foreach ($s in $skills) {
    $file = Join-Path $s.FullName "SKILL.md"
    if (-not (Test-Path $file)) { throw "缺 SKILL.md：$($s.Name)" }
    $text = Get-Content $file -Raw -Encoding UTF8
    if (-not $text.StartsWith("---")) { throw "缺 frontmatter：$($s.Name)" }
    $head = ($text -split "---", 3)[1]
    if ($head -notmatch "(?m)^name:\s*(\S+)\s*$") { throw "缺 name：$($s.Name)" }
    if ($Matches[1] -ne $s.Name) { throw "name 与目录名不一致：$($s.Name) / $($Matches[1])" }
    if ($head -notmatch "(?m)^description:\s*\S") { throw "缺 description：$($s.Name)" }
}
Write-Host "frontmatter 校验通过：$($skills.Count) 个 skill"

# 2. 测试
if (-not $SkipTest) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { throw "找不到 python，无法跑测试；确认环境后可用 -SkipTest 跳过" }
    $env:PYTHONUTF8 = "1"
    # unittest 把用例名写到 stderr；Stop 策略下原生命令的 stderr 会被当成终止错误
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & python (Join-Path $RepoRoot "tests\test_scissors.py") 2>&1 | Out-Null
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($rc -ne 0) { throw "测试未通过（退出码 $rc），已中止安装" }
    Write-Host "测试通过"
}

# 3. 复制，并清掉已经不在源目录里的旧 skill（删掉的 skill 不该留在磁盘上）
New-Item -ItemType Directory -Force -Path $DestRoot | Out-Null
$names = $skills.Name
Get-ChildItem $DestRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "scissorhands*" -and $names -notcontains $_.Name } |
    ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force
        Write-Host "已移除过期的 skill：$($_.Name)"
    }
foreach ($s in $skills) {
    $target = Join-Path $DestRoot $s.Name
    if ((Test-Path $target) -and -not $Force) {
        throw "已存在 $target，用 -Force 覆盖"
    }
    Copy-Item $s.FullName $target -Recurse -Force
}
Write-Host "skill 已安装到 $DestRoot"

# 4. User 作用域额外放一份完整仓库，供 skill 里的 tools/scissors.py 路径使用
if ($Scope -eq "User") {
    $home_ = Join-Path $env:USERPROFILE ".dsh\scissorhands"
    if ((Test-Path $home_) -and $Force) { Remove-Item $home_ -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $home_ | Out-Null
    foreach ($item in @("tools", "tests", "docs", "skills")) {
        Copy-Item (Join-Path $RepoRoot $item) (Join-Path $home_ $item) -Recurse -Force
    }
    Copy-Item (Join-Path $RepoRoot "README.md") (Join-Path $home_ "README.md") -Force
    Copy-Item (Join-Path $RepoRoot "install.ps1") (Join-Path $home_ "install.ps1") -Force
    Write-Host "工具已放置到 $home_\tools\scissors.py"
}

Write-Host ""
Write-Host "下一步：开新会话，skill 列表里会出现 $($skills.Count) 个 scissorhands-* ；"
Write-Host "交付前跑 python tools/scissors.py verify --original A --edited B ，退出码 0 才算过。"
