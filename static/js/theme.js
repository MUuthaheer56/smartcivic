/* SmartCivic - Theme, Print and Export Helpers */

function printDashboard() {
  window.print();
}

// Global hook for before-after slider draggable event binding
const BeforeAfterSlider = {
  init: function(sliderId) {
    const slider = document.getElementById(sliderId);
    if (!slider) return;
    
    const divider = slider.querySelector('.slider-divider');
    const afterImg = slider.querySelector('.slider-img.after');
    
    if (!divider || !afterImg) return;
    
    let isDragging = false;
    
    const onMove = (e) => {
      if (!isDragging) return;
      
      const rect = slider.getBoundingClientRect();
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      let x = clientX - rect.left;
      
      // Boundaries
      if (x < 0) x = 0;
      if (x > rect.width) x = rect.width;
      
      const percentage = (x / rect.width) * 100;
      
      divider.style.left = `${percentage}%`;
      afterImg.style.width = `${percentage}%`;
    };
    
    const startDrag = () => { isDragging = true; };
    const stopDrag = () => { isDragging = false; };
    
    divider.addEventListener('mousedown', startDrag);
    divider.addEventListener('touchstart', startDrag);
    
    window.addEventListener('mousemove', onMove);
    window.addEventListener('touchmove', onMove);
    
    window.addEventListener('mouseup', stopDrag);
    window.addEventListener('touchend', stopDrag);
  }
};
