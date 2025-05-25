/**
 * Chart utility functions for the analysis page
 */

// Function to create a doughnut chart for category analysis
function createCategoryChart(ctx, categories, values) {
    // Set of colors for the chart
    const backgroundColors = [
        'rgba(255, 99, 132, 0.7)',
        'rgba(54, 162, 235, 0.7)',
        'rgba(255, 206, 86, 0.7)',
        'rgba(75, 192, 192, 0.7)',
        'rgba(153, 102, 255, 0.7)',
        'rgba(255, 159, 64, 0.7)',
        'rgba(199, 199, 199, 0.7)',
        'rgba(83, 102, 255, 0.7)',
        'rgba(40, 159, 64, 0.7)',
        'rgba(210, 105, 30, 0.7)'
    ];
    
    return new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: categories,
            datasets: [{
                data: values,
                backgroundColor: backgroundColors.slice(0, categories.length),
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                }
            }
        }
    });
}

// Function to create a bar chart for monthly analysis
function createMonthlyChart(ctx, months, values) {
    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: months,
            datasets: [{
                label: '月份消費',
                data: values,
                backgroundColor: 'rgba(54, 162, 235, 0.7)',
                borderColor: 'rgba(54, 162, 235, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

// Function to create a bar chart for income vs expense comparison
function createIncomeExpenseChart(ctx, incomeAmount, expenseAmount) {
    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['收入', '支出'],
            datasets: [{
                data: [incomeAmount, expenseAmount],
                backgroundColor: [
                    'rgba(75, 192, 192, 0.7)',
                    'rgba(255, 99, 132, 0.7)'
                ],
                borderColor: [
                    'rgba(75, 192, 192, 1)',
                    'rgba(255, 99, 132, 1)'
                ],
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: true
                }
            }
        }
    });
}

// Function to calculate total income and expense from transaction data
function calculateTotals(transactions) {
    let totalIncome = 0;
    let totalExpense = 0;
    
    transactions.forEach(transaction => {
        if (transaction.type === '收入') {
            totalIncome += transaction.amount;
        } else {
            totalExpense += transaction.amount;
        }
    });
    
    return {
        income: totalIncome,
        expense: totalExpense,
        balance: totalIncome - totalExpense
    };
}

// Function to group transactions by category
function groupByCategory(transactions) {
    const categories = {};
    
    transactions.forEach(transaction => {
        if (transaction.type === '支出') {
            const category = transaction.category;
            
            if (!categories[category]) {
                categories[category] = 0;
            }
            
            categories[category] += transaction.amount;
        }
    });
    
    return categories;
}

// Function to group transactions by month
function groupByMonth(transactions) {
    const months = {};
    
    transactions.forEach(transaction => {
        // Extract year and month from the date
        const date = new Date(transaction.date);
        const yearMonth = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
        
        if (!months[yearMonth]) {
            months[yearMonth] = 0;
        }
        
        if (transaction.type === '支出') {
            months[yearMonth] += transaction.amount;
        }
    });
    
    return months;
}

// Function to find the top spending category
function findTopCategory(categoryData) {
    let topCategory = null;
    let topAmount = 0;
    
    for (const category in categoryData) {
        if (categoryData[category] > topAmount) {
            topAmount = categoryData[category];
            topCategory = category;
        }
    }
    
    return {
        name: topCategory || '-',
        amount: topAmount
    };
}
