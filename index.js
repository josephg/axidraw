// const es = require('event-stream')
const {spawn} = require('child_process')
const clean = require('./clean')

const paperSize = { // w,h in MM
  a5: [210, 148],
  a4: [297, 210],
}

const roundish = n => Math.round(n*10000)/10000

const defaultCallback = (err) => {
  if (err) console.error('Error plotting:', err)
}

// Paths is a list of paths (lines). Each line is a list of points [x,y].
// viewbox is either [left, top, width, height] or {t,r,b,l}.
// opts:
// - preview: (bool)
// - paperSize: [210, 148] in mm
// - noclean: don't clean the paths
function plot(paths, viewbox, opts, callback) {
  if (typeof opts === 'function') [opts, callback] = [{}, opts]
  if (opts == null) opts = {}

  const [paperW,paperH] = opts.paperSize ? (paperSize[opts.paperSize] || opts.paperSize) : paperSize.a5
  const strokeWidth = opts.strokeWidth || 0.1

  if (!Array.isArray(viewbox)) {
    const {l,r,t,b} = viewbox
    viewbox = [l, t, r-l, b-t]
  }

  if (!opts.noclean) paths = clean(paths, viewbox)

  const svg = `<?xml version="1.0" encoding="UTF-8" ?>
<svg xmlns="http://www.w3.org/2000/svg" width="${paperW}mm" height="${paperH}mm" viewBox="${viewbox.join(' ')}">
  ${paths.map(path => `<path fill="none" stroke="black" stroke-width="${strokeWidth}mm" d="M${path.map(p => p.map(roundish).join(' ')).join(' L')}"></path>`)}
</svg>`

  // console.log(svg)

  plotSvg(svg, opts, callback)
}


function plotSvg(svg, opts, callback = defaultCallback) {
  const args = ['axidraw.py']
  if (opts.preview) args.push('--previewOnly=true')
   args.push('--reportTime=true')
  args.push('-')

  const proc = spawn('python', args, {
    cwd: __dirname + '/pycode',
    stdio: [null, 'inherit', 'inherit']
  })

  proc.stdin.write(svg)
  proc.stdin.end()

  if (!opts.nopipe) {
    // proc.stdout.pipe(process.stdout)
    // proc.stderr.pipe(process.stderr)
  }

  // Actually, the process seems to always returns 0 unless it crashes.
  proc.on('exit', (code, signal) => {
    callback(code === 0 ? null : new Error(code), signal)
  })

}

module.exports = {plot, plotSvg}

if (require.main === module) {
  // console.log('yooo')

  plot([[[-100,-100], [100,100]]], [-707, -500, 1414, 1000], {preview:true}, (err, out) => {
    if (err) throw err
    console.log('done')
  })

  // const fs = require('fs')
  // plotSvg(fs.readFileSync('/Users/josephg/Downloads/rope_8414.svg', 'utf8'), {preview:true})
  // plotSvg(fs.readFileSync('/Users/josephg/src/b/svg/foo.svg', 'utf8'), {preview:true})
}
