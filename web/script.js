const WHATSAPP_NUMBER = "595981000000";

function buildWhatsAppLink(message) {
  const encodedMessage = encodeURIComponent(message || "Hola, quiero más información.");
  return `https://wa.me/${WHATSAPP_NUMBER}?text=${encodedMessage}`;
}

document.querySelectorAll(".whatsapp-link").forEach((link) => {
  const message = link.dataset.message || "Hola, quiero más información sobre Autobots.";
  link.href = buildWhatsAppLink(message);
  link.rel = "noopener";
  link.target = "_blank";
});

document.querySelectorAll("details").forEach((item) => {
  item.addEventListener("toggle", () => {
    if (!item.open) return;

    document.querySelectorAll("details").forEach((otherItem) => {
      if (otherItem !== item) {
        otherItem.removeAttribute("open");
      }
    });
  });
});
