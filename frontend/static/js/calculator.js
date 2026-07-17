// FinCheck - Interactive EMI Calculator Module

document.addEventListener('DOMContentLoaded', () => {
    initCalculator();
});

function initCalculator() {
    const loanAmountSlider = document.getElementById('calc-amount');
    const interestRateSlider = document.getElementById('calc-rate');
    const tenureSlider = document.getElementById('calc-tenure');
    
    const loanAmountInput = document.getElementById('calc-amount-input');
    const interestRateInput = document.getElementById('calc-rate-input');
    const tenureInput = document.getElementById('calc-tenure-input');
    
    if (!loanAmountSlider || !interestRateSlider || !tenureSlider ||
        !loanAmountInput || !interestRateInput || !tenureInput) return;
    
    const emiDisplay = document.getElementById('calc-emi-val');
    const principalDisplay = document.getElementById('calc-principal-val');
    const interestDisplay = document.getElementById('calc-interest-val');
    const totalDisplay = document.getElementById('calc-total-val');
    
    const chips = document.querySelectorAll('.chip-btn');
    
    function updateCalculator(source) {
        let amount = parseFloat(loanAmountInput.value) || 0;
        let rateAnnual = parseFloat(interestRateInput.value) || 0;
        let tenureYears = parseFloat(tenureInput.value) || 0;
        
        // Handle source-specific synchronization
        if (source === 'slider-amount') {
            amount = parseFloat(loanAmountSlider.value);
            loanAmountInput.value = amount;
        } else if (source === 'input-amount') {
            // Update slider position (constrained to slider min/max)
            loanAmountSlider.value = Math.max(
                parseFloat(loanAmountSlider.min), 
                Math.min(parseFloat(loanAmountSlider.max), amount)
            );
        } else if (source === 'slider-rate') {
            rateAnnual = parseFloat(interestRateSlider.value);
            interestRateInput.value = rateAnnual;
        } else if (source === 'input-rate') {
            interestRateSlider.value = Math.max(
                parseFloat(interestRateSlider.min),
                Math.min(parseFloat(interestRateSlider.max), rateAnnual)
            );
        } else if (source === 'slider-tenure') {
            tenureYears = parseFloat(tenureSlider.value);
            tenureInput.value = tenureYears;
        } else if (source === 'input-tenure') {
            tenureSlider.value = Math.max(
                parseFloat(tenureSlider.min),
                Math.min(parseFloat(tenureSlider.max), tenureYears)
            );
        }
        
        const tenureMonths = tenureYears * 12;
        
        // Update chip active states based on amount
        chips.forEach(chip => {
            if (parseInt(chip.getAttribute('data-value')) === amount) {
                chip.classList.add('active');
            } else {
                chip.classList.remove('active');
            }
        });
        
        // Calculate EMI
        const monthlyRate = (rateAnnual / 100) / 12;
        let emi = 0;
        
        if (tenureMonths > 0) {
            if (monthlyRate === 0) {
                emi = amount / tenureMonths;
            } else {
                emi = (amount * monthlyRate * Math.pow(1 + monthlyRate, tenureMonths)) / 
                      (Math.pow(1 + monthlyRate, tenureMonths) - 1);
            }
        }
        
        const totalPayment = emi * tenureMonths;
        const totalInterest = Math.max(0, totalPayment - amount);
        
        // Display values
        emiDisplay.textContent = `₹${Math.round(emi).toLocaleString()}`;
        principalDisplay.textContent = `₹${amount.toLocaleString()}`;
        interestDisplay.textContent = `₹${Math.round(totalInterest).toLocaleString()}`;
        totalDisplay.textContent = `₹${Math.round(totalPayment).toLocaleString()}`;
    }
    
    // Add event listeners for sliders
    loanAmountSlider.addEventListener('input', () => updateCalculator('slider-amount'));
    interestRateSlider.addEventListener('input', () => updateCalculator('slider-rate'));
    tenureSlider.addEventListener('input', () => updateCalculator('slider-tenure'));
    
    // Add event listeners for numeric text inputs
    loanAmountInput.addEventListener('input', () => updateCalculator('input-amount'));
    interestRateInput.addEventListener('input', () => updateCalculator('input-rate'));
    tenureInput.addEventListener('input', () => updateCalculator('input-tenure'));
    
    // Add event listeners for chips
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            const val = parseInt(chip.getAttribute('data-value'));
            loanAmountInput.value = val;
            loanAmountSlider.value = val;
            updateCalculator('input-amount');
        });
    });
    
    // Initial run
    updateCalculator();
}
