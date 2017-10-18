# Axidraw tools

This is a simple nodejs wrapper around the axidraw inkscape python extension. The axidraw extension (and parts of inkscape) are in the pycode directory.

To use, you'll need a working version of python and the following python libraries installed:

```
easy_install pyserial
easy_install lxml
```

# API

```javascript
const axidraw = require('axidraw')
```

## axidraw.plot(paths, viewbox, opts, callback)

Plot specified paths with the axidraw. Paths is a list of lists of points. Eg, `[[[0,0], [100, 100]]]`

viewbox is a list of `[x, y, w, h]` of the actual content to draw. Eg, `[-707, -500, 1414, 1000]`

Opts:

- `preview` (bool): Preview mode, where nothing is actually sent to the plotter. Plotted SVG returned.
- `paperSize`: Either a string ('a4', 'a5') or a pair of `[width, height]` in mm. Eg, `[210, 148]`.
- `noclean` (bool): Don't clean up the paths (trim and join) before plotting

## axidraw.plotSvg(svg, opts, callback)

Plot an SVG string directly.


# License

All nodejs code is licensed under the ISC
Python code is copyright the respective authors.

- Axidraw code [licensed under the GPLv2](https://github.com/evil-mad/axidraw/blob/master/LICENSE)
- Inkscape code [licensed under GPL2 and LGPL2.1](https://github.com/inkscape/inkscape/tree/bzr-original)

