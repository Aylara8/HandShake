// 1. ENGINE SETUP
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 5000);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);

// Ensure the container exists before appending
const container = document.getElementById('canvas-container');
if (container) {
    container.appendChild(renderer.domElement);
} else {
    console.error("CRITICAL: #canvas-container not found in HTML!");
}

// 2. LIGHTING (Increased intensity so things aren't black)
const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
scene.add(ambientLight);
const sunLight = new THREE.PointLight(0xffffff, 2, 1000);
sunLight.position.set(20, 20, 20);
scene.add(sunLight);

// 3. THE STARS (Increased size and spread)
const starGeo = new THREE.BufferGeometry();
const starCount = 5000;
const posArray = new Float32Array(starCount * 3);
for(let i=0; i < starCount * 3; i++) {
    posArray[i] = (Math.random() - 0.5) * 2000; 
}
starGeo.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({ size: 2, color: 0xffffff }));
scene.add(stars);

// 4. THE PLANET (With a bright color so it's not hidden in the dark)
const marsGeo = new THREE.SphereGeometry(5, 64, 64);
const marsMat = new THREE.MeshStandardMaterial({ color: 0xff4500 }); // Bright Orange
const mars = new THREE.Mesh(marsGeo, marsMat);
mars.userData = { id: 1 };
scene.add(mars);

// 5. CAMERA POSITION (Move it back so we see everything)
camera.position.z = 50; 

// 6. ANIMATION LOOP
function animate() {
    requestAnimationFrame(animate);
    mars.rotation.y += 0.005;
    stars.rotation.y += 0.0002;
    renderer.render(scene, camera);
}
animate();

// 7. CLICK HANDLER (Bulletproof)
window.addEventListener('click', (event) => {
    const mouse = new THREE.Vector2(
        (event.clientX / window.innerWidth) * 2 - 1,
        -(event.clientY / window.innerHeight) * 2 + 1
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(scene.children);

    if (intersects.length > 0) {
        const obj = intersects.find(i => i.object.userData.id);
        if (obj) {
            window.location.href = `/planet/${obj.object.userData.id}`;
        }
    }
});