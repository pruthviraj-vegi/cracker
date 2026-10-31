let printInProgress = false;

function handlePrint() {
    if (printInProgress) return;
    printInProgress = true;
    setTimeout(() => {
        window.print();
    }, 100);
}

document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
        window.close();
    }
    if (event.key === 'Enter') {
        handlePrint();
    }
});

window.addEventListener('afterprint', function () {
    printInProgress = false;
    window.close();
});

window.addEventListener('load', function () {
    setTimeout(() => {
        window.print();
    }, 500);
});