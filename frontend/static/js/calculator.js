// FinCheck - Interactive EMI Calculator Module

document.addEventListener('DOMContentLoaded', () => {
    initCalculator();
});

function initCalculator() {
    const loanAmountSlider = document.getElementById('calc-amount');
    const interestRateSlider = document.getElementById('calc-rate');
    const tenureSlider = document.getElementById('calc-tenure');
    
    if (!loanAmountSlider || !interestRateSlider || !tenureSlider) return;
    
    const loanAmountVal = document.getElementById('calc-amount-val');
    const interestRateVal = document.getElementById('calc-rate-val');
    const tenureVal = document.getElementById('calc-tenure-val');
    
    const emiDisplay = document.getElementById('calc-emi-val');
    const principalDisplay = document.getElementById('calc-principal-val');
    const interestDisplay = document.getElementById('calc-interest-val');
    const totalDisplay = document.getElementById('calc-total-val');
    
    function updateCalculator() {
        const amount = parseFloat(loanAmountSlider.value);
        const rateAnnual = parseFloat(interestRateSlider.value);
        const tenureYears = parseFloat(tenureSlider.value);
        const tenureMonths = tenureYears * 12;
        
        // Update labels
        loanAmountVal.textContent = `₹${amount.toLocaleString()}`;
        interestRateVal.textContent = `${rateAnnual}%`;
        tenureVal.textContent = `${tenureYears} Years (${tenureMonths} Mos)`;
        
        // Calculate EMI
        const monthlyRate = (rateAnnual / 100) / 12;
        let emi = 0;
        
        if (monthlyRate === 0) {
            emi = amount / tenureMonths;
        } else {
            emi = (amount * monthlyRate * Math.pow(1 + monthlyRate, tenureMonths)) / 
                  (Math.pow(1 + monthlyRate, tenureMonths) - 1);
        }
        
        const totalPayment = emi * tenureMonths;
        const totalInterest = totalPayment - amount;
        
        // Display values
        emiDisplay.textContent = `₹${Math.round(emi).toLocaleString()}`;
        principalDisplay.textContent = `₹${amount.toLocaleString()}`;
        interestDisplay.textContent = `₹${Math.round(totalInterest).toLocaleString()}`;
        totalDisplay.textContent = `₹${Math.round(totalPayment).toLocaleString()}`;
    }
    
    // Add event listeners for sliders
    loanAmountSlider.addEventListener('input', updateCalculator);
    interestRateSlider.addEventListener('input', updateCalculator);
    tenureSlider.addEventListener('input', updateCalculator);
    
    // Initial run
    updateCalculator();
}
