/**
 * SmartCivic Field Worker Real-Road Navigation Module
 * Consumes OpenStreetMap tiles and renders real road routing geometry via OSRM.
 */
class SmartCivicNavigation {
    constructor(mapContainerId, initialCoords = [12.9716, 77.5946]) {
        this.map = L.map(mapContainerId).setView(initialCoords, 14);
        
        // OpenStreetMap Tile Layer
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(this.map);

        this.routeLayer = null;
        this.workerMarker = null;
        this.complaintMarker = null;
    }

    setWorkerLocation(lat, lon) {
        if (this.workerMarker) {
            this.workerMarker.setLatLng([lat, lon]);
        } else {
            this.workerMarker = L.marker([lat, lon], {
                title: "Worker Current Location",
                icon: L.divIcon({
                    className: 'worker-loc-pin',
                    html: '<div style="background:#2563eb;width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 4px rgba(0,0,0,0.5);"></div>'
                })
            }).addTo(this.map);
        }
    }

    async renderRoadRouteToComplaint(workerCoords, complaintCoords, complaintInfo) {
        const [wLat, wLon] = workerCoords;
        const [cLat, cLon] = complaintCoords;

        this.setWorkerLocation(wLat, wLon);

        if (this.complaintMarker) {
            this.map.removeLayer(this.complaintMarker);
        }

        this.complaintMarker = L.marker([cLat, cLon])
            .addTo(this.map)
            .bindPopup(`<b>${complaintInfo.title}</b><br>Priority: ${complaintInfo.priority}<br>${complaintInfo.address || ''}`)
            .openPopup();

        // Clear prior route polyline
        if (this.routeLayer) {
            this.map.removeLayer(this.routeLayer);
        }

        try {
            // Call server-side routing gateway
            const response = await fetch(`/api/v1/routing/calculate?origin_lat=${wLat}&origin_lon=${wLon}&dest_lat=${cLat}&dest_lon=${cLon}`);
            const data = await response.json();

            if (data.status === "SUCCESS" && data.geometry) {
                // Render real road geometry
                this.routeLayer = L.geoJSON(data.geometry, {
                    style: {
                        color: '#2563eb',
                        weight: 5,
                        opacity: 0.85
                    }
                }).addTo(this.map);

                this.map.fitBounds(this.routeLayer.getBounds(), { padding: [40, 40] });

                // Update UI dashboard HUD
                document.getElementById('route-distance').innerText = `${(data.distance_meters / 1000).toFixed(2)} km`;
                document.getElementById('route-eta').innerText = `${data.eta_minutes} mins`;
                document.getElementById('route-type').innerText = data.is_real_road ? 'Road Network' : 'Direct Line (Offline)';
            }
        } catch (err) {
            console.error("Road route fetch error, falling back to direct line:", err);
            this.routeLayer = L.polyline([[wLat, wLon], [cLat, cLon]], {
                color: '#dc2626',
                dashArray: '6, 8',
                weight: 4
            }).addTo(this.map);
        }
    }
}
