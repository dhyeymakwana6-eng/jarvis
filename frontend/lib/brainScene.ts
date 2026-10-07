import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import type { OrbSceneApi } from "@/lib/orbScene";

// ULTRON: an electric-blue neural network shaped like a brain. Signals travel along
// the connections and light up the neurons they reach; thinking makes
// the network fire faster and harder. Same API as the JARVIS orb, so
// gestures, keys and chat drive either scene.

const HOME_POSITION = new THREE.Vector3(0, 0.3, 4.3);
const FOV = 55;
// Half the brain's width plus a margin, in world units.
const HALF_WIDTH = 1.75;

/**
 * Starting camera position. Narrow (portrait) screens see less
 * horizontally, so the camera backs off until the whole brain fits.
 */
function homePosition(aspect: number): THREE.Vector3 {
  const halfHorizontalFov = Math.atan(Math.tan(THREE.MathUtils.degToRad(FOV / 2)) * aspect);
  const fitDistance = HALF_WIDTH / Math.tan(halfHorizontalFov);
  return HOME_POSITION.clone().setLength(Math.max(HOME_POSITION.length(), fitDistance));
}
const MIN_DISTANCE = 0.8;
const MAX_DISTANCE = 40;

// Network size. Kept modest so phones can run it.
const CORTEX_NEURONS = 480;
const INNER_NEURONS = 90;
const CEREBELLUM_NEURONS = 45;
const STEM_NEURONS = 12;
const LINKS_PER_NEURON = 4;
const MAX_LINK_LENGTH = 0.5;
const MAX_PULSES = 160;

interface ActivityLevel {
  spawnPerSecond: number; // new signals started per second
  chainChance: number; // chance a signal continues from the neuron it reaches
  pulseSpeed: number; // world units per second
}

const IDLE: ActivityLevel = { spawnPerSecond: 10, chainChance: 0.6, pulseSpeed: 1.2 };
const THINKING: ActivityLevel = { spawnPerSecond: 34, chainChance: 0.82, pulseSpeed: 2.6 };

// Electric blue at rest, near-white cyan where signals fire.
const BASE_COLOR = new THREE.Color(0.06, 0.3, 0.75);
const FIRE_COLOR = new THREE.Color(0.65, 0.95, 1.0);
const LINK_BASE = new THREE.Color(0.03, 0.16, 0.42);
const LINK_FIRE = new THREE.Color(0.45, 0.9, 1.0);

// Deterministic randomness, so the brain has the same shape on every load.
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Soft round sprite for points (default points are squares). */
function glowTexture(): THREE.CanvasTexture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(255,255,255,0.8)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

/** Neuron positions: two wrinkled hemispheres, cerebellum and stem. */
function brainPoints(rand: () => number): THREE.Vector3[] {
  const points: THREE.Vector3[] = [];

  const onEllipsoid = (rx: number, ry: number, rz: number, shell: [number, number]) => {
    const u = rand() * 2 - 1;
    const theta = rand() * Math.PI * 2;
    const s = Math.sqrt(1 - u * u);
    const dir = new THREE.Vector3(s * Math.cos(theta), u, s * Math.sin(theta));
    // Gyri: a low-frequency wrinkle on the surface.
    const wrinkle = 1 + 0.06 * Math.sin(theta * 7) * Math.sin(u * 9);
    const r = (shell[0] + rand() * (shell[1] - shell[0])) * wrinkle;
    return new THREE.Vector3(dir.x * rx * r, dir.y * ry * r, dir.z * rz * r);
  };

  const flattenBottom = (p: THREE.Vector3, floor: number) => {
    if (p.y < floor) p.y = floor + (p.y - floor) * 0.35;
    return p;
  };

  for (const side of [-1, 1]) {
    const center = new THREE.Vector3(side * 0.66, 0.08, 0);
    for (let i = 0; i < CORTEX_NEURONS / 2; i++) {
      points.push(flattenBottom(onEllipsoid(0.66, 0.92, 1.25, [0.86, 1.0]), -0.42).add(center));
    }
    for (let i = 0; i < INNER_NEURONS / 2; i++) {
      points.push(flattenBottom(onEllipsoid(0.66, 0.92, 1.25, [0.25, 0.8]), -0.42).add(center));
    }
  }

  const cerebellum = new THREE.Vector3(0, -0.62, -0.88);
  for (let i = 0; i < CEREBELLUM_NEURONS; i++) {
    points.push(onEllipsoid(0.72, 0.3, 0.38, [0.7, 1.0]).add(cerebellum));
  }

  for (let i = 0; i < STEM_NEURONS; i++) {
    const t = i / (STEM_NEURONS - 1);
    points.push(new THREE.Vector3((rand() - 0.5) * 0.12, -0.55 - t * 0.85, -0.35 + t * 0.12));
  }

  return points;
}

/** Each neuron links to its nearest neighbours (deduplicated). */
function linkNeurons(points: THREE.Vector3[]): [number, number][] {
  const links = new Map<string, [number, number]>();

  points.forEach((p, i) => {
    const nearest = points
      .map((q, j) => ({ j, d: p.distanceTo(q) }))
      .filter(({ j, d }) => j !== i && d < MAX_LINK_LENGTH)
      .sort((a, b) => a.d - b.d)
      .slice(0, LINKS_PER_NEURON);

    for (const { j } of nearest) {
      const key = i < j ? `${i}-${j}` : `${j}-${i}`;
      links.set(key, i < j ? [i, j] : [j, i]);
    }
  });

  return [...links.values()];
}

export function createBrainScene(container: HTMLElement): OrbSceneApi {
  const width = container.clientWidth;
  const height = container.clientHeight;
  const rand = mulberry32(1729);

  // ——— SCENE ———
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(FOV, width / height, 0.1, 500);
  camera.position.copy(homePosition(camera.aspect));

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.85;
  container.appendChild(renderer.domElement);

  // ——— POST PROCESSING ———
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));

  const bloom = new UnrealBloomPass(new THREE.Vector2(width, height), 1.5, 0.55, 0.12);
  composer.addPass(bloom);

  // Chromatic split + a cold blue grade (the JARVIS orb grades amber).
  const gradePass = new ShaderPass({
    uniforms: {
      tDiffuse: { value: null },
      uTime: { value: 0 },
      uIntensity: { value: 0.004 },
    },
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform sampler2D tDiffuse;
      uniform float uTime;
      uniform float uIntensity;
      varying vec2 vUv;
      void main() {
        vec2 dir = vUv - vec2(0.5);
        float offset = uIntensity * length(dir);
        float flicker = 1.0 + 0.025 * sin(uTime * 41.0) * sin(uTime * 5.1);
        vec4 cr = texture2D(tDiffuse, vUv + dir * offset);
        vec4 cg = texture2D(tDiffuse, vUv);
        vec4 cb = texture2D(tDiffuse, vUv - dir * offset);
        vec3 color = vec3(cr.r * 0.8, cg.g, cb.b) * flicker;
        gl_FragColor = vec4(mix(color, color * vec3(0.6, 0.95, 1.25), 0.35), 1.0);
      }
    `,
  });
  composer.addPass(gradePass);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.04;
  controls.minDistance = MIN_DISTANCE;
  controls.maxDistance = MAX_DISTANCE;
  controls.zoomSpeed = 1.4;
  controls.enablePan = false;

  const sprite = glowTexture();

  // ——— BRAIN ———
  const brain = new THREE.Group();
  brain.rotation.y = -0.6; // three-quarter view, so both hemispheres read
  scene.add(brain);

  const neurons = brainPoints(rand);
  const links = linkNeurons(neurons);
  const neighbours: number[][] = neurons.map(() => []);
  links.forEach(([a, b], index) => {
    neighbours[a].push(index);
    neighbours[b].push(index);
  });

  // How recently each neuron fired (decays to 0).
  const activation = new Float32Array(neurons.length);

  const neuronGeo = new THREE.BufferGeometry().setFromPoints(neurons);
  const neuronColors = new Float32Array(neurons.length * 3);
  neuronGeo.setAttribute("color", new THREE.BufferAttribute(neuronColors, 3));
  const neuronPoints = new THREE.Points(
    neuronGeo,
    new THREE.PointsMaterial({
      size: 0.085,
      map: sprite,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  brain.add(neuronPoints);

  const linkPositions = new Float32Array(links.length * 6);
  links.forEach(([a, b], i) => {
    neurons[a].toArray(linkPositions, i * 6);
    neurons[b].toArray(linkPositions, i * 6 + 3);
  });
  const linkGeo = new THREE.BufferGeometry();
  linkGeo.setAttribute("position", new THREE.BufferAttribute(linkPositions, 3));
  const linkColors = new Float32Array(links.length * 6);
  linkGeo.setAttribute("color", new THREE.BufferAttribute(linkColors, 3));
  brain.add(
    new THREE.LineSegments(
      linkGeo,
      new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.85,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    ),
  );

  // Signals travelling along links.
  interface Pulse {
    link: number;
    from: number;
    to: number;
    t: number; // 0..1 along the link
    length: number;
  }
  const pulses: Pulse[] = [];
  const pulsePositions = new Float32Array(MAX_PULSES * 3);
  const pulseGeo = new THREE.BufferGeometry();
  pulseGeo.setAttribute("position", new THREE.BufferAttribute(pulsePositions, 3));
  pulseGeo.setDrawRange(0, 0);
  brain.add(
    new THREE.Points(
      pulseGeo,
      new THREE.PointsMaterial({
        size: 0.11,
        map: sprite,
        color: 0xd8f6ff,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    ),
  );

  function startPulse(link: number, from: number) {
    if (pulses.length >= MAX_PULSES) return;
    const [a, b] = links[link];
    const to = from === a ? b : a;
    pulses.push({ link, from, to, t: 0, length: neurons[a].distanceTo(neurons[b]) });
  }

  function spawnRandomPulse() {
    const from = Math.floor(rand() * neurons.length);
    const options = neighbours[from];
    if (options.length) startPulse(options[Math.floor(rand() * options.length)], from);
  }

  // Faint core glow, like activity deep in the brain.
  const core = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: sprite,
      color: 0x2a8cff,
      transparent: true,
      opacity: 0.18,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  core.scale.setScalar(2.4);
  brain.add(core);

  // Ambient dust around the brain.
  const dust: THREE.Vector3[] = [];
  for (let i = 0; i < 500; i++) {
    const r = 3 + rand() * 7;
    const theta = rand() * Math.PI * 2;
    const phi = Math.acos(rand() * 2 - 1);
    dust.push(new THREE.Vector3(r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta)));
  }
  const dustPoints = new THREE.Points(
    new THREE.BufferGeometry().setFromPoints(dust),
    new THREE.PointsMaterial({
      size: 0.035,
      map: sprite,
      color: 0x12406e,
      transparent: true,
      opacity: 0.7,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }),
  );
  scene.add(dustPoints);

  // ——— CAMERA CONTROL (same behaviour as the orb) ———
  const sphericalScratch = new THREE.Spherical();
  const offsetScratch = new THREE.Vector3();

  function rotateBy(deltaTheta: number, deltaPhi: number) {
    offsetScratch.copy(camera.position).sub(controls.target);
    sphericalScratch.setFromVector3(offsetScratch);
    sphericalScratch.theta -= deltaTheta;
    sphericalScratch.phi = THREE.MathUtils.clamp(sphericalScratch.phi - deltaPhi, 0.05, Math.PI - 0.05);
    sphericalScratch.makeSafe();
    offsetScratch.setFromSpherical(sphericalScratch);
    camera.position.copy(controls.target).add(offsetScratch);
    camera.lookAt(controls.target);
  }

  function zoomBy(factor: number) {
    offsetScratch.copy(camera.position).sub(controls.target);
    offsetScratch.setLength(THREE.MathUtils.clamp(offsetScratch.length() * factor, MIN_DISTANCE, MAX_DISTANCE));
    camera.position.copy(controls.target).add(offsetScratch);
  }

  function resetView() {
    camera.position.copy(homePosition(camera.aspect));
    controls.target.set(0, 0, 0);
    camera.lookAt(controls.target);
    controls.update();
  }

  // ——— ANIMATION ———
  const timer = new THREE.Timer();
  timer.connect(document);
  let rafId = 0;
  let disposed = false;
  let thinking = false;
  // 0 = idle, 1 = thinking; eased so the network ramps up and down.
  let intensity = 0;
  let spawnDebt = 0;
  let t = 0;
  const color = new THREE.Color();

  function setThinking(value: boolean) {
    thinking = value;
  }

  function animate(timestamp?: number) {
    if (disposed) return;
    rafId = requestAnimationFrame(animate);
    timer.update(timestamp);
    const dt = Math.min(timer.getDelta(), 0.1);
    t += dt;
    intensity += ((thinking ? 1 : 0) - intensity) * Math.min(1, dt * 2.5);

    const lerp = (a: number, b: number) => a + (b - a) * intensity;
    const spawnRate = lerp(IDLE.spawnPerSecond, THINKING.spawnPerSecond);
    const chainChance = lerp(IDLE.chainChance, THINKING.chainChance);
    const speed = lerp(IDLE.pulseSpeed, THINKING.pulseSpeed);

    // Start new signals.
    spawnDebt += spawnRate * dt;
    while (spawnDebt >= 1) {
      spawnRandomPulse();
      spawnDebt -= 1;
    }

    // Move signals; on arrival, fire the neuron and maybe continue.
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i];
      p.t += (speed * dt) / Math.max(p.length, 0.05);
      if (p.t < 1) continue;

      activation[p.to] = Math.min(1.6, activation[p.to] + 1);
      pulses.splice(i, 1);

      if (rand() < chainChance) {
        const onward = neighbours[p.to].filter((link) => link !== p.link);
        if (onward.length) startPulse(onward[Math.floor(rand() * onward.length)], p.to);
      }
    }

    pulses.forEach((p, i) => {
      const a = neurons[p.from];
      const b = neurons[p.to];
      pulsePositions[i * 3] = a.x + (b.x - a.x) * p.t;
      pulsePositions[i * 3 + 1] = a.y + (b.y - a.y) * p.t;
      pulsePositions[i * 3 + 2] = a.z + (b.z - a.z) * p.t;
    });
    pulseGeo.attributes.position.needsUpdate = true;
    pulseGeo.setDrawRange(0, pulses.length);

    // Neuron and link colours follow recent firing.
    const decay = Math.exp(-dt * 2.8);
    for (let i = 0; i < neurons.length; i++) {
      activation[i] *= decay;
      color.copy(BASE_COLOR).lerp(FIRE_COLOR, Math.min(1, activation[i]));
      color.toArray(neuronColors, i * 3);
    }
    neuronGeo.attributes.color.needsUpdate = true;

    links.forEach(([a, b], i) => {
      color.copy(LINK_BASE).lerp(LINK_FIRE, Math.min(1, activation[a] * 0.8));
      color.toArray(linkColors, i * 6);
      color.copy(LINK_BASE).lerp(LINK_FIRE, Math.min(1, activation[b] * 0.8));
      color.toArray(linkColors, i * 6 + 3);
    });
    linkGeo.attributes.color.needsUpdate = true;

    // Slow drift; a little faster while thinking.
    brain.rotation.y += dt * (0.07 + intensity * 0.12);
    brain.position.y = Math.sin(t * 0.6) * 0.04;
    dustPoints.rotation.y += dt * 0.01;

    const heartbeat = Math.pow(Math.max(0, Math.sin(t * (1.1 + intensity * 1.6))), 6);
    (core.material as THREE.SpriteMaterial).opacity = 0.12 + heartbeat * 0.12 + intensity * 0.12;
    bloom.strength = 1.35 + heartbeat * 0.25 + intensity * 0.25;
    gradePass.uniforms.uTime.value = t;

    controls.update();
    composer.render();
  }

  animate();

  // ——— RESIZE ———
  function onResize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    composer.setSize(w, h);
  }
  window.addEventListener("resize", onResize);

  // ——— CLEANUP ———
  function dispose() {
    disposed = true;
    cancelAnimationFrame(rafId);
    timer.dispose();
    window.removeEventListener("resize", onResize);
    controls.dispose();
    scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      mesh.geometry?.dispose();
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const mat of mats) mat?.dispose();
    });
    sprite.dispose();
    composer.dispose();
    renderer.dispose();
    renderer.domElement.remove();
  }

  return {
    rotateBy,
    zoomBy,
    zoomIn: () => zoomBy(0.65),
    zoomOut: () => zoomBy(1.55),
    resetView,
    setThinking,
    dispose,
  };
}
