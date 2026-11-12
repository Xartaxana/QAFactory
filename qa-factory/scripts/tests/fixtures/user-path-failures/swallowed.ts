export async function addToCart(id: string) {
  try {
    const response = await fetch(`/api/cart/${id}`, { method: "POST" });
    return await response.json();
  } catch (error) {
    console.error(error);
  }
}
