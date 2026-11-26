# Third-party software in the Windows package

The components below retain their upstream licenses. The Python runtime's own
`LICENSE.txt` is at the package root. Python wheels retain their notices in
`site-packages/*dist-info`. The license of the Scorpion application does not
replace these terms.

| Component | Version and license | Source and build information |
| --- | --- | --- |
| CPython | 3.14.10, PSF license and component notices | [Python release](https://www.python.org/downloads/release/python-31410/) · [source tag](https://github.com/python/cpython/tree/v3.14.10) |
| PyQt6 | 6.12.0, GPL-3.0-only, as reported by the packaged wheel | [PyQt6 source distribution](https://pypi.org/project/PyQt6/6.12.0/#files) · [publisher's license information](https://www.riverbankcomputing.com/software/pyqt/) |
| Qt | 6.12.0, LGPL v3 as reported by the packaged Qt wheel, with module-specific notices | [Qt 6.12.0 source](https://download.qt.io/official_releases/qt/6.12/6.12.0/single/) · packaged Qt notice in `pyqt6_qt6-6.12.0.dist-info` |
| PyQt6 SIP | 13.13.0, BSD-2-Clause | [SIP source distribution](https://pypi.org/project/PyQt6-sip/13.13.0/#files) |
| FFmpeg and FFprobe | N-127709-g5993347a1b-20261019, GPL build with version 3 enabled | [FFmpeg source revision](https://github.com/FFmpeg/FFmpeg/tree/5993347a1b84a88892ac66a8ef981f7f18e9997c) · [binary build recipe revision](https://github.com/yt-dlp/FFmpeg-Builds/tree/bf23782fa09c1ab08a3c13f2f1508d7ef0e620c6) · [original build run](https://github.com/yt-dlp/FFmpeg-Builds/actions/runs/39311218581) |
| aria2 | 1.37.0, GPL-2.0-or-later with the upstream OpenSSL exception | [Matching release binaries and source archives](https://github.com/aria2/aria2/releases/tag/release-1.37.0) · `aria2-GPL-2.0.txt` · `aria2-OpenSSL-exception.txt` |
| QuickJS-ng | 0.17.0, MIT | [Release assets and source](https://github.com/quickjs-ng/quickjs/releases/tag/v0.17.0) · `QuickJS-ng-MIT.txt` |

Other Python dependencies are identified and pinned in `requirements.txt` in
the Scorpion source. Their upstream license texts and copyright notices are
preserved in the installed wheel metadata.

The public FFmpeg source revision is only one part of the corresponding
source. The build recipe and original build run identify dependency sources
and build configuration. The run's `download-cache` artifact also contains
inputs used by the pipeline. A time-limited or sign-in-only artifact link is
not a durable public source mirror. See [FFmpeg's licensing guidance](https://ffmpeg.org/legal.html)
and the version 3 [GNU license terms](https://www.gnu.org/licenses/gpl-3.0.html).
