// 1. SOUND & HUD SETUP
const warpSound = new Audio('https://codesandbox.io/api/v1/sandboxes/f7s3z/assets/warp.mp3');
const reticle = document.getElementById('reticle');

// 2. SCENE & LIGHTING
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 5000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.getElementById('canvas-container').appendChild(renderer.domElement);

const sunLight = new THREE.DirectionalLight(0xffffff, 2);
sunLight.position.set(5, 3, 10);
scene.add(sunLight);
scene.add(new THREE.AmbientLight(0x222222));

// 3. THE PLANETS (Mars & Jupiter)
const loader = new THREE.TextureLoader();

function createPlanet(size, xPos, textureUrl, id) {
    const geo = new THREE.SphereGeometry(size, 64, 64);
    const mat = new THREE.MeshStandardMaterial({ color: 0x444444 });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.x = xPos;
    mesh.userData = { id: id };
    scene.add(mesh);

    loader.load(textureUrl, (tex) => {
        mesh.material.map = tex;
        mesh.material.needsUpdate = true;
    });
    return mesh;
}

// Mars (Small)
const mars = createPlanet(2.5, 0, 'https://upload.wikimedia.org/wikipedia/commons/3/3b/Mars_Hubble.jpg', 1);
// Jupiter (Large - positioned to the right)
const jupiter = createPlanet(6.0, 40, 'https://upload.wikimedia.org/wikipedia/commons/e/e2/Jupiter.jpg', 2);

// 4. THE GALAXY
const starGeo = new THREE.BufferGeometry();
const starCount = 6000;
const posArray = new Float32Array(starCount * 3);
for(let i=0; i<starCount*3; i++) { posArray[i] = (Math.random() - 0.5) * 3000; }
starGeo.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ size: 1.5, color: 0xffffff }));
scene.add(stars);

camera.position.z = 60;

// 5. MOUSE & CLICK LOGIC
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

window.addEventListener('mousemove', (e) => {
    // Move the HTML Reticle
    reticle.style.left = e.clientX + 'px';
    reticle.style.top = e.clientY + 'px';
    
    // Update Raycaster Mouse
    mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;
});

window.addEventListener('click', () => {
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(scene.children);

    if (intersects.length > 0 && intersects[0].object.userData.id) {
        const target = intersects[0].object;
        warpSound.play().catch(() => {}); // Play sound
        
        // Cinematic Warp Animation
        gsap.to(camera.position, {
            x: target.position.x,
            y: target.position.y,
            z: target.position.z + 10,
            duration: 2,
            ease: "power4.inOut",
            onComplete: () => window.location.href = `/planet/${target.userData.id}`
        });
    }
});

// 6. ANIMATION LOOP
function animate() {
    requestAnimationFrame(animate);
    mars.rotation.y += 0.01;
    jupiter.rotation.y += 0.005;
    stars.rotation.y += 0.0008;
    renderer.render(scene, camera);
}
animate();