from flask import request
from flask_socketio import join_room, leave_room, emit
from app import socketio

@socketio.on('connect', namespace='/civic')
def on_connect():
    print(f"Client connected to namespace /civic: {request.sid}")

@socketio.on('disconnect', namespace='/civic')
def on_disconnect():
    print(f"Client disconnected from namespace /civic: {request.sid}")

@socketio.on('join_room', namespace='/civic')
def on_join(data):
    room = data.get('room')
    if room:
        join_room(room)
        print(f"Client {request.sid} joined room: {room}")
        emit('room_joined', {'message': f"Successfully joined room {room}"}, to=request.sid, namespace='/civic')

@socketio.on('worker_location_update', namespace='/civic')
def on_worker_location(data):
    # data: { worker_id, lat, lng, community_id }
    community_id = data.get('community_id')
    if community_id:
        emit('worker_location', data, room=f"authority_{community_id}", namespace='/civic')
        print(f"Worker {data.get('worker_id')} updated location to {data.get('lat')}, {data.get('lng')} in room authority_{community_id}")
