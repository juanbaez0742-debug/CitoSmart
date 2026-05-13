document.getElementById("formAnalisis").addEventListener("submit", function(e) {
    e.preventDefault();

    const imagenId = document.getElementById("imagen_id").value;

    fetch("/analisis/", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            imagen_id: imagenId
        })
    })
    .then(response => response.json())
    .then(data => {
        document.getElementById("resultado").innerText = data.resultado;
    })
    .catch(error => console.error("Error:", error));
});