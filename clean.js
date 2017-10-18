const pathtrim = require('pathtrim')

const pointInBB = ([x, y], {l, r, t, b}) => (x >= l && x <= r && y >= t && y <= b)

const clamp = (x, a, b) => Math.min(Math.max(x, a), b)
const vlen = (x, y) => Math.sqrt(x*x + y*y)
const dist2 = ([x0, y0], [x1, y1]) => vlen(x0-x1, y0-y1)
const distsq = ([x0, y0], [x1, y1]) => (x0-x1)*(x0-x1) + (y0-y1)*(y0-y1)

const samePoint = ([x0, y0], [x1, y1]) => x0 === x1 && y0 === y1
const isWithinDist = (p0, p1, dist) => samePoint(p0, p1) || distsq(p0, p1) < dist*dist
// const isVeryClose = (p0, p1) => samePoint(p0, p1) || isWithinDist(p0, p1, 0.1)

/*
const trimPaths = (paths, bb) => {
  const out = []

  paths.forEach(p => {
    for (let i = 1; i < p.length; i++) {
      const a = p[i-1], b = p[i]
      //if (i == 1) console.log(a)

      if (!pointInBB(a, bb) || !pointInBB(b, bb)) continue

      let last
      const lastPath = out.length ? out[out.length-1] : null
      if (lastPath === null || lastPath[lastPath.length-1] !== a) {
        last = [a]
        out.push(last)
      } else {
        last = lastPath
      }
      last.push(b)
    }
  })

  return out
}*/

const trimPaths = (paths, viewbox) => {
  const [x,y,w,h] = viewbox
  return pathtrim(paths, [
    [[x,y], [x,y+h], [x+w,y+h], [x+w,y]]
  ], true)
}

const optimizePathOrder = paths => {
  // This doesn't do travelling salesman or anything, it just reverses the
  // order of paths if it makes sense to. This is good for when the plotter is
  // drawing a series of parallell-ish lines.
  for (let i = 1; i < paths.length; i++) {
    const endpoint = paths[i-1][paths[i-1].length-1]

    const d1 = dist2(endpoint, paths[i][0])
    const d2 = dist2(endpoint, paths[i][paths[i].length-1])
    if (d2 < d1) paths[i].reverse()
  }
  return paths
}


const joinPaths = (paths, epsilon) => {
  // The efficient version of this would be to use AABB trees, but eh. N^2 should be fine.
  outer: for (let i = 0; i < paths.length - 1; i++) {
    const p1 = paths[i]
    for (let k = i+1; k < paths.length;) {
      const p2 = paths[k]

      let join = true
      if (isWithinDist(p1[0], p2[0], epsilon)) {
        p1.reverse()
      } else if (isWithinDist(p1[p1.length-1], p2[0], epsilon)) {
      } else if (isWithinDist(p1[0], p2[p2.length - 1], epsilon)) {
        // Could join them the other way but eh.
        p1.reverse()
        p2.reverse()
      } else if (isWithinDist(p1[p1.length-1], p2[p2.length - 1], epsilon)) {
        p2.reverse()
      } else {
        join = false
      }

      if (join) {
        p1.pop()
        p1.push.apply(p1, p2)
        // Move the newly joined path to the end so other paths can still glom on to it.
        paths.splice(k, 1)
        paths.splice(i, 1)
        paths.push(p1)
        i--
        continue outer

        // This would be faster, but less pretty when drawing.
        //paths[k] = paths[paths.length - 1]
        //paths.length--
      } else {
        k++
      }
    }
  }
  return paths
}


module.exports = (paths, viewbox) => {

  // console.log('paths', paths, viewbox)
  const [x,y,w,h] = viewbox
  const epsilon = w / 10000

  console.warn('optimize paths:', paths.length, 'points', paths.reduce((len, v) => len + v.length, 0))
  paths = trimPaths(paths, viewbox)
  console.warn('trimmed paths:', paths.length, 'points', paths.reduce((len, v) => len + v.length, 0))
  // console.log('p2', paths)
  paths = optimizePathOrder(paths)
  console.warn('optimze order:', paths.length, 'points', paths.reduce((len, v) => len + v.length, 0))
  // console.warn('joinPaths')
  paths = joinPaths(paths, epsilon)
  console.warn('optimization complete', 'Paths:', paths.length, 'points', paths.reduce((len, v) => len + v.length, 0))
  return paths
}
