#!/usr/bin/env python3
"""Minimal .vsix packager (a .vsix is a zip: [Content_Types].xml,
extension.vsixmanifest and the extension under extension/)."""
import json, os, re, sys, zipfile
from xml.sax.saxutils import escape

here = os.path.dirname(os.path.abspath(__file__))
pkg = json.load(open(os.path.join(here, "package.json")))
server_src = open(os.path.join(here, "..", "server", "basilisk_lsp.py")).read()
m = re.search(r'^VERSION = "([^"]+)"', server_src, re.M)
if not m or m.group(1) != pkg["version"]:
    sys.exit(f"version mismatch: server {m and m.group(1)} vs vscode/package.json {pkg['version']}")
skip_top = {"build.sh", "package_vsix.py", ".gitignore", ".vscodeignore", "package-lock.json"}

files = []
for d, dirs, fs in os.walk(here):
    rel = os.path.relpath(d, here)
    dirs[:] = [x for x in dirs if not x.startswith(".")]
    for f in fs:
        r = os.path.normpath(os.path.join(rel, f))
        if r in skip_top or f.endswith(".vsix") or "/test/" in "/" + r + "/" and "node_modules" not in r:
            continue
        files.append(r)
if "server/basilisk_lsp.py" not in files or not os.path.isdir(os.path.join(here, "node_modules", "vscode-languageclient")):
    sys.exit("run build.sh (needs server/ copied and npm install)")

exts = sorted({os.path.splitext(f)[1].lower() for f in files if os.path.splitext(f)[1]} | {".vsixmanifest"})
ctype = {".json": "application/json", ".js": "application/javascript", ".vsixmanifest": "text/xml",
         ".md": "text/markdown", ".xml": "text/xml"}
types = ('<?xml version="1.0" encoding="utf-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
         + "".join(f'<Default Extension="{e}" ContentType="{ctype.get(e, "application/octet-stream")}"/>' for e in exts)
         + "</Types>")
manifest = f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{pkg['name']}" Version="{pkg['version']}" Publisher="{pkg['publisher']}" />
    <DisplayName>{escape(pkg['displayName'])}</DisplayName>
    <Description xml:space="preserve">{escape(pkg['description'])}</Description>
    <Tags>basilisk,c</Tags>
    <Categories>{escape(",".join(pkg['categories']))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg['engines']['vscode']}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="{",".join(pkg.get('extensionKind', ['workspace']))}" />
    </Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
'''
out = os.path.join(here, f"{pkg['name']}-{pkg['version']}.vsix")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", types)
    z.writestr("extension.vsixmanifest", manifest)
    for f in sorted(files):
        z.write(os.path.join(here, f), "extension/" + f)
print(f"{out}: {len(files)} files")
