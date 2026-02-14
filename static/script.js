document.addEventListener('DOMContentLoaded', () => {
    const puzzleContainer = document.querySelector('.puzzle-container');
    const puzzleScene = document.querySelector('.puzzle-scene');

    // Scroll Interaction: Snap pieces together
    window.addEventListener('scroll', () => {
        const scrollY = window.scrollY;
        // Threshold to snap
        if (scrollY > 50) {
            puzzleContainer.classList.add('puzzle-solved');
        } else {
            puzzleContainer.classList.remove('puzzle-solved');
        }

        // Slight rotation on scroll
        if (puzzleScene) {
            puzzleScene.style.transform = `rotateX(${-15 + scrollY * 0.05}deg) rotateY(${25 + scrollY * 0.1}deg)`;
        }
    });

    // Mouse Interaction: Tilt Scene
    if (puzzleContainer && puzzleScene) {
        puzzleContainer.addEventListener('mousemove', (e) => {
            const rect = puzzleContainer.getBoundingClientRect();
            const x = (e.clientX - rect.left) / rect.width;
            const y = (e.clientY - rect.top) / rect.height;

            // -1 to 1 range
            const mouseX = (x - 0.5) * 2;
            const mouseY = (y - 0.5) * 2;

            // Base rotation: RotateX(-15), RotateY(25)
            // Add mouse influence
            const tiltX = -15 + (-mouseY * 10);
            const tiltY = 25 + (mouseX * 10);

            puzzleScene.style.transform = `rotateX(${tiltX}deg) rotateY(${tiltY}deg)`;
        });

        puzzleContainer.addEventListener('mouseleave', () => {
            // Reset to base or let scroll take over
            const scrollY = window.scrollY;
            const baseX = -15 + scrollY * 0.05;
            const baseY = 25 + scrollY * 0.1;
            puzzleScene.style.transform = `rotateX(${baseX}deg) rotateY(${baseY}deg)`;
        });
    }
    // Resume Upload Logic
    const fileInput = document.getElementById('file-input');
    const fileName = document.getElementById('file-name');
    const selectedFileDiv = document.getElementById('selected-file');
    const uploadArea = document.getElementById('upload-area');

    if (fileInput) {
        fileInput.addEventListener('change', function (e) {
            if (this.files && this.files[0]) {
                fileName.textContent = this.files[0].name;
                selectedFileDiv.style.display = 'flex';
                uploadArea.style.borderColor = '#4f46e5';
                uploadArea.style.backgroundColor = '#f5f3ff';
            }
        });

        // Drag and drop effects
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '#4f46e5';
            uploadArea.style.backgroundColor = '#f5f3ff';
        });

        uploadArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            uploadArea.style.borderColor = '#e2e8f0';
            uploadArea.style.backgroundColor = 'transparent';
        });
    }
});
