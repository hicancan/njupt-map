$ErrorActionPreference = 'Stop'
$assetRoot = Join-Path (Split-Path (Split-Path $PSScriptRoot)) 'projects/blender/materials'
$manifest = [System.Collections.Generic.List[object]]::new()
function Save-AssetFile($file, $relative) {
    $destination = Join-Path $assetRoot $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    if (-not (Test-Path -LiteralPath $destination) -or (Get-Item -LiteralPath $destination).Length -ne $file.size) {
        Invoke-WebRequest -Uri $file.url -OutFile $destination -TimeoutSec 240
    }
    $hash = (Get-FileHash -LiteralPath $destination -Algorithm MD5).Hash.ToLowerInvariant()
    if ($hash -ne $file.md5) { throw "Checksum mismatch: $relative" }
    $manifest.Add([pscustomobject]@{path=$relative.Replace('\','/');url=$file.url;size=$file.size;md5=$hash;license='CC0-1.0'})
    Write-Output "Verified $relative"
}
foreach ($id in @('grass_ground','asphalt_02','rock_tile_floor')) {
    $data = Invoke-RestMethod "https://api.polyhaven.com/files/$id"
    $directory = Join-Path $assetRoot $id
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $data | ConvertTo-Json -Depth 30 | Set-Content (Join-Path $directory 'source-api.json') -Encoding utf8
    foreach ($map in @('Diffuse','nor_gl','Rough')) {
        $file = $data.$map.'2k'.jpg
        Save-AssetFile $file "$id/$([System.IO.Path]::GetFileName($file.url))"
    }
}
$treeId = 'jacaranda_tree'
$treeData = Invoke-RestMethod "https://api.polyhaven.com/files/$treeId"
$treeDirectory = Join-Path $assetRoot $treeId
New-Item -ItemType Directory -Force -Path $treeDirectory | Out-Null
$treeData | ConvertTo-Json -Depth 30 | Set-Content (Join-Path $treeDirectory 'source-api.json') -Encoding utf8
$treeFile = $treeData.blend.'1k'.blend
Save-AssetFile $treeFile "$treeId/$([System.IO.Path]::GetFileName($treeFile.url))"
foreach ($include in $treeFile.include.PSObject.Properties) { Save-AssetFile $include.Value "$treeId/$($include.Name)" }
[pscustomobject]@{provider='Poly Haven';retrieved_at=(Get-Date -Format o);license='CC0-1.0';license_url='https://polyhaven.com/license';notes='Textures are authentic scanned generic materials. Jacaranda used as a generic broadleaf visual surrogate; not evidence of campus tree species. One shared geometry/material source is instanced.';assets=@('grass_ground','asphalt_02','rock_tile_floor','jacaranda_tree');files=$manifest} | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $assetRoot 'manifest.json') -Encoding utf8
