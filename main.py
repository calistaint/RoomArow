import pygame
import socket
import pickle
import threading
import sys
import ctypes
import os
import struct
import queue
import math
import random
import numpy as np
if sys.platform == 'win32':
    try:
        # 1 = Process_System_DPI_Aware (Prevents blur, but might be small on 4k)
        # 2 = Process_Per_Monitor_DPI_Aware (Best for Win 10/11)
        ctypes.windll.shcore.SetProcessDpiAwareness(2) 
    except Exception:
        # Fallback for older Windows versions or if shcore isn't available
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except:
            pass

def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base_path, relative_path)

# --- Constants ---
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60

# Colors (Ported from Arow.py)
WHITE = (255, 255, 255)
BLACK = (30, 30, 30) # Background/Floor
RED = (255, 50, 50)
GREEN = (0, 255, 0)
BLUE = (100, 150, 255)
YELLOW = (255, 255, 0)
ORANGE = (255, 165, 0)
CYAN = (0, 255, 255)
PURPLE = (180, 0, 255)
GOLD = (255, 215, 0)
SILVER = (192, 192, 192)
GRID_COLOR = (25, 25, 30) # Dark void
GRAY = (70, 70, 70) # Undiscovered rooms on minimap
PLAYER_COLOR = (200, 220, 255)
DARK_GRAY = (40, 40, 40) # Walls

# Network Defaults
DEFAULT_PORT = 5555
HEADER_SIZE = 4
ROOM_SIZE = 1000 # Logical size of a room
TILE_SIZE = 60
PARTICLE_LIMIT = 300

# Room Types
ROOM_START = 0
ROOM_NORMAL = 1
ROOM_BOSS = 2
ROOM_CHEST = 3

class Room:
    def __init__(self, x, y, type=ROOM_NORMAL):
        self.grid_x = x
        self.grid_y = y
        self.type = type
        self.doors = {'N': False, 'S': False, 'E': False, 'W': False}
        self.cleared = False
        self.enemies = []
        self.projectiles = []
        self.activation_timer = 0  # Frames until enemies activate (90 = 1.5s at 60fps)
        self.floor_rocks = []  # Generated floor details


    def get_world_rect(self):
        # Returns the world space rect for this room
        # Compact layout: Rooms touch each other
        offset_x = self.grid_x * ROOM_SIZE
        offset_y = self.grid_y * ROOM_SIZE
        return pygame.Rect(offset_x, offset_y, ROOM_SIZE, ROOM_SIZE)

    def spawn_enemies_for_room(self, game):
        # Determine enemy count/type based on room type
        rect = self.get_world_rect()
        
        # Boss rooms spawn a Boss instead of regular enemies
        if self.type == ROOM_BOSS:
            bx = rect.centerx
            by = rect.centery
            game.spawn_boss(bx, by, room_coords=(self.grid_x, self.grid_y))
            return
        
        # Normal/Chest rooms spawn regular enemies
        base_count = random.randint(2, 5)
        
        # Difficulty scaling: regular enemy count multiplier only starts after floor 8
        floor_num = getattr(game, 'floor_number', 1)
        if floor_num >= 9:
            # apply scaling relative to floors after 8
            enemy_multiplier = 1.2 ** ((floor_num - 8) // 4)
        else:
            enemy_multiplier = 1.0
        count = int(base_count * enemy_multiplier)
        
        # All enemy types with weighted chances (more common first)
        enemy_types = ["charger", "charger", "shooter", "shooter", "kamikaze", "splitter", "tank", "turret", "sniper"]
        
        # Progressive difficulty: Add new enemies based on floor
        if floor_num >= 3: enemy_types.extend(["teleporter", "teleporter"])
        if floor_num >= 4: enemy_types.extend(["shielder", "shielder"])
        if floor_num >= 3: enemy_types.extend(["teleporter", "teleporter"])
        if floor_num >= 4: enemy_types.extend(["shielder", "shielder"])
        if floor_num >= 5: 
            # Limit dodgers to 2 per room
            current_dodgers = [e for e in game.enemies.values() if e.room_coords == (self.grid_x, self.grid_y) and e.type == "dodger"]
            if len(current_dodgers) < 2:
                enemy_types.extend(["dodger", "dodger"])
        if floor_num >= 6: enemy_types.extend(["healer", "healer"])
        if floor_num >= 7: enemy_types.extend(["phaser", "phaser"])
        for i in range(count):
            # Spawn away from doors (200px margin instead of 100)
            ex = random.randint(rect.left + 200, rect.right - 200)
            ey = random.randint(rect.top + 200, rect.bottom - 200)
            etype = random.choice(enemy_types)
            # Dodger gets double activation delay
            if etype == "dodger":
                enemy_id = game.spawn_enemy(ex, ey, etype, room_coords=(self.grid_x, self.grid_y))
                if enemy_id in game.enemies:
                    game.enemies[enemy_id].activation_timer = 180  # 2x default (90)
            else:
                game.spawn_enemy(ex, ey, etype, room_coords=(self.grid_x, self.grid_y))

    def get_walls(self):
        # Return strict wall rects, considering doors
        rect = self.get_world_rect()
        walls = []
        thickness = 50
        door_size = 150
        
        # Top Wall
        if self.doors['N']:
            walls.append(pygame.Rect(rect.left, rect.top, (rect.width - door_size)//2, thickness))
            walls.append(pygame.Rect(rect.right - (rect.width - door_size)//2, rect.top, (rect.width - door_size)//2, thickness))
        else:
            walls.append(pygame.Rect(rect.left, rect.top, rect.width, thickness))
            
        # Bottom Wall
        if self.doors['S']:
            walls.append(pygame.Rect(rect.left, rect.bottom - thickness, (rect.width - door_size)//2, thickness))
            walls.append(pygame.Rect(rect.right - (rect.width - door_size)//2, rect.bottom - thickness, (rect.width - door_size)//2, thickness))
        else:
             walls.append(pygame.Rect(rect.left, rect.bottom - thickness, rect.width, thickness))
             
        # Left Wall
        if self.doors['W']:
            walls.append(pygame.Rect(rect.left, rect.top, thickness, (rect.height - door_size)//2))
            walls.append(pygame.Rect(rect.left, rect.bottom - (rect.height - door_size)//2, thickness, (rect.height - door_size)//2))
        else:
             walls.append(pygame.Rect(rect.left, rect.top, thickness, rect.height))
             
        # Right Wall
        if self.doors['E']:
             walls.append(pygame.Rect(rect.right - thickness, rect.top, thickness, (rect.height - door_size)//2))
             walls.append(pygame.Rect(rect.right - thickness, rect.bottom - (rect.height - door_size)//2, thickness, (rect.height - door_size)//2))
        else:
             walls.append(pygame.Rect(rect.right - thickness, rect.top, thickness, rect.height))
             
        return walls
        
    def get_doors(self):
         rect = self.get_world_rect()
         doors = []
         thickness = 50
         door_size = 150
         
         if self.doors['N']: 
             doors.append(pygame.Rect(rect.centerx - door_size//2, rect.top, door_size, thickness))
         if self.doors['S']:
             doors.append(pygame.Rect(rect.centerx - door_size//2, rect.bottom - thickness, door_size, thickness))
         if self.doors['W']:
             doors.append(pygame.Rect(rect.left, rect.centery - door_size//2, thickness, door_size))
         if self.doors['E']:
             doors.append(pygame.Rect(rect.right - thickness, rect.centery - door_size//2, thickness, door_size))
             
         return doors

class Chest:
    def __init__(self, x, y):
        self.rect = pygame.Rect(x, y, 40, 40)
        self.opened = False
        self.color = (139, 69, 19) # Brown
        
    def draw(self, surface, camera_offset):
        draw_rect = self.rect.move(-camera_offset.x, -camera_offset.y)
        color = (100, 100, 100) if self.opened else self.color
        pygame.draw.rect(surface, color, draw_rect)
        pygame.draw.rect(surface, (255, 215, 0), draw_rect, 2) # Gold outline

class DungeonGenerator:
    def __init__(self, seed=None):
        if seed: random.seed(seed)
        self.rooms = {} # (x,y): Room
        self.chests = []
    
    def generate(self, num_rooms=10):
        boss_pos = (0,0)
        # Retry loop to ensure we generate a good map
        for attempt in range(20):
            self.rooms = {}
            self.chests = []
            # Start Room
            start_room = Room(0, 0, ROOM_START)
            start_room.cleared = True
            self.rooms[(0,0)] = start_room
            
            queue = [(0,0)]
            occupied = set([(0,0)])
            
            count = 1
            # Expansion loop
            while count < num_rooms and queue:
                # Pick random room from queue to expand from (more organic than BFS popping 0)
                idx = random.randint(0, len(queue)-1)
                cx, cy = queue[idx]
                
                # Try all 4 directions
                dirs = [(0, -1, 'N', 'S'), (0, 1, 'S', 'N'), (-1, 0, 'W', 'E'), (1, 0, 'E', 'W')]
                random.shuffle(dirs)
                
                expansion_success = False
                for dx, dy, door_me, door_them in dirs:
                    if count >= num_rooms: break
                    nx, ny = cx + dx, cy + dy
                    
                    if (nx, ny) not in occupied:
                        # Chance to place room (higher chance to avoid early termination)
                        if random.random() < 0.6:
                            new_room = Room(nx, ny, ROOM_NORMAL)
                            self.rooms[(nx, ny)] = new_room
                            occupied.add((nx, ny))
                            queue.append((nx, ny))
                            
                            # Connect
                            self.rooms[(cx, cy)].doors[door_me] = True
                            new_room.doors[door_them] = True
                            count += 1
                            expansion_success = True
                    elif (nx, ny) in self.rooms:
                         # Chance to connect to existing neighbor (loops)
                         if random.random() < 0.15:
                             self.rooms[(cx, cy)].doors[door_me] = True
                             self.rooms[(nx, ny)].doors[door_them] = True
                
                # If this room didn't expand, maybe remove from queue to avoid getting stuck?
                # But we might want to branch later. Let's just keep it.
                # To ensure progress, if queue is empty/stuck, we might fail.
                
                # Optimization: Remove from queue if all neighbors full/tried? 
                # For now just randomness handles it.
            
            # if count >= 6 check removed, we do this check below inside the main logic block

        
            # Check if map is valid size (at least 5 rooms including start)
            # If not, and we have retries left, continue
            if count < 5 and attempt < 19:
                continue

            # Assign Boss Room (Furthest leaf node preferred)
            max_dist = 0
            boss_pos = (0,0)
            
            # Score rooms by distance + being a leaf node
            candidates = []
            for (rx, ry), room in self.rooms.items():
                if (rx, ry) == (0,0): continue # Not start
                dist = abs(rx) + abs(ry)
                degree_count = sum(1 for d in room.doors.values() if d)
                
                # Prefer leaf nodes (degree 1) for boss significantly
                score = dist * 10
                if degree_count == 1: score += 100000 # Huge bonus for leaf node
                
                candidates.append((score, (rx, ry)))
            
            if candidates:
                # Sort by score desc
                candidates.sort(key=lambda x: x[0], reverse=True)
                boss_pos = candidates[0][1]
                self.rooms[boss_pos].type = ROOM_BOSS
                break # Success! Break the retry loop
            elif attempt < 19:
                 continue # No candidates for boss (unlikely if >1 room)
            
        # Place Chests
        for pos, room in self.rooms.items():
            if room.type == ROOM_CHEST:
                rect = room.get_world_rect()
                self.chests.append(Chest(rect.centerx - 20, rect.centery - 20))
            elif room.type == ROOM_NORMAL:
                if random.random() < 0.2:
                    rect = room.get_world_rect()
                    self.chests.append(Chest(rect.centerx - 20, rect.centery - 20))

        print(f"Generated {len(self.rooms)} rooms. Boss at {boss_pos}")
        return self.rooms, self.chests

class NetworkManager:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.is_host = False
        self.connected = False
        self.client_id = None
        self.clients = []  # List of client sockets (Host only)
        self.lock = threading.Lock()
        self.data_queue = queue.Queue()
        self.running = True

    def host_game(self, port=DEFAULT_PORT):
        try:
            self.socket.bind(('0.0.0.0', port))
            self.socket.listen()
            self.is_host = True
            print(f"Server started on port {port}")
            threading.Thread(target=self._accept_connections, daemon=True).start()
            return True
        except Exception as e:
            print(f"Failed to host: {e}")
            return False

    def join_game(self, ip, port=DEFAULT_PORT):
        try:
            self.socket.connect((ip, port))
            self.connected = True
            self.is_host = False
            print(f"Connected to {ip}:{port}")
            threading.Thread(target=self._receive_loop, args=(self.socket,), daemon=True).start()
            return True
        except Exception as e:
            print(f"Failed to join: {e}")
            return False

    def send(self, data):
        """Sends data to connected peer(s)."""
        try:
            serialized = pickle.dumps(data)
            message = struct.pack("!I", len(serialized)) + serialized
            
            if self.is_host:
                with self.lock:
                    for client in self.clients:
                        try:
                            client.sendall(message)
                        except:
                            self.clients.remove(client)
            elif self.connected:
                 self.socket.sendall(message)
        except Exception as e:
            print(f"Send error: {e}")

    def get_events(self):
        """Returns a list of received data objects."""
        events = []
        try:
            while True:
                events.append(self.data_queue.get_nowait())
        except queue.Empty:
            pass
        return events

    def _accept_connections(self):
        while self.running:
            try:
                conn, addr = self.socket.accept()
                print(f"New connection from {addr}")
                with self.lock:
                    self.clients.append(conn)
                threading.Thread(target=self._receive_loop, args=(conn,), daemon=True).start()
            except Exception as e:
                print(f"Accept error: {e}")
                break

    def _receive_loop(self, conn):
        """Standard length-prefixed message receiver."""
        try:
            while self.running:
                # Read 4-byte Header
                header_data = self._recv_all(conn, HEADER_SIZE)
                if not header_data: break
                
                msg_len = struct.unpack("!I", header_data)[0]
                
                # Read Body
                body_data = self._recv_all(conn, msg_len)
                if not body_data: break
                
                # Unpickle
                data = pickle.loads(body_data)
                self.data_queue.put((data, conn))
        except Exception as e:
            print(f"Receive loop error: {e}")
        finally:
            conn.close()
            with self.lock:
                if conn in self.clients: self.clients.remove(conn)
            # Signal disconnect to Game
            self.data_queue.put(({"type": "DISCONNECT"}, conn))

    def shutdown(self):
        self.running = False
        try:
            with self.lock:
                for c in list(self.clients):
                    try:
                        c.close()
                    except:
                        pass
                self.clients.clear()
        except:
            pass
        try:
            self.socket.close()
        except:
            pass

    def _recv_all(self, conn, n):
        """Helper to receive exactly n bytes."""
        data = b''
        while len(data) < n:
            packet = conn.recv(n - len(data))
            if not packet: return None
            data += packet
        return data

# --- Particle System (Ported from Arow.py) ---
particles = pygame.sprite.Group()

class Particle(pygame.sprite.Sprite):
    def __init__(self, pos, color, min_speed, max_speed, min_life, max_life):
        super().__init__()
        angle, speed = random.uniform(0, 2 * math.pi), random.uniform(min_speed, max_speed)
        self.velocity = [math.cos(angle) * speed, math.sin(angle) * speed]
        self.lifespan = random.randint(min_life, max_life)
        self.initial_lifespan = self.lifespan
        self.size = random.randint(2, 5)
        self.image = pygame.Surface((self.size * 2, self.size * 2), pygame.SRCALPHA)
        pygame.draw.circle(self.image, color, (self.size, self.size), self.size)
        self.rect, self.pos = self.image.get_rect(center=pos), list(pos)

    def update(self):
        self.pos[0] += self.velocity[0]
        self.pos[1] += self.velocity[1]
        self.rect.center = self.pos
        self.lifespan -= 1
        if self.lifespan <= 0: self.kill()
        self.image.set_alpha(int(255 * (self.lifespan / self.initial_lifespan)))

def create_particles(position, count, color, min_speed, max_speed, min_life, max_life):
    if len(particles) > PARTICLE_LIMIT - count: return
    for _ in range(count):
        particles.add(Particle(position, color, min_speed, max_speed, min_life, max_life))

# --- EnergyBeam for Sniper (Ported from Arow.py) ---
class EnergyBeam:
    def __init__(self, pos, angle, length=2000, width=40):
        # Create beam that starts from pos and extends in direction of angle
        unrotated_surf = pygame.Surface((length, width), pygame.SRCALPHA)
        center_y = width // 2
        pygame.draw.rect(unrotated_surf, PURPLE, (0, 0, length, width), border_radius=center_y)
        pygame.draw.rect(unrotated_surf, CYAN, (0, center_y - width // 4, length, width // 2), border_radius=width // 4)
        pygame.draw.rect(unrotated_surf, WHITE, (0, center_y - width // 8, length, width // 4), border_radius=width // 8)
        self.image = pygame.transform.rotate(unrotated_surf, angle)
        # Position rect so beam starts from pos, not centered on it
        self.rect = self.image.get_rect()
        # Calculate offset so beam starts from the sniper position
        offset = pygame.math.Vector2(length/2, 0).rotate(-angle)
        self.rect.center = pos + offset
        self.lifespan = 30
        self.max_lifespan = 30
        self.damage = 2
        self.spawn_room = (int(pos[0] // ROOM_SIZE), int(pos[1] // ROOM_SIZE))
        self.start_pos = pos
        self.angle = angle
        self.length = length

    def update(self):
        self.lifespan -= 1
        if self.lifespan <= 0: return True # Dead
        self.image.set_alpha(int(255 * (self.lifespan / self.max_lifespan)))
        return False

    def draw(self, surface, camera_offset):
        draw_rect = self.rect.move(-camera_offset.x, -camera_offset.y)
        surface.blit(self.image, draw_rect)

class Bullet:
    def __init__(self, x, y, angle, owner_id, speed=10, color=YELLOW, bullet_type="normal", damage=10, spawn_room=None):
        self.pos = pygame.math.Vector2(x, y)
        self.angle = angle
        self.speed = speed
        self.owner_id = owner_id
        self.velocity = pygame.math.Vector2(self.speed, 0).rotate(-angle)
        self.lifetime = 120 # Frames
        self.color = color
        self.bullet_type = bullet_type
        self.damage = damage
        self.exploded = False
        self.explosion_radius = 0
        self.explosion_timer = 0
        self.hit_ids = set()
        self.spawn_room = spawn_room if spawn_room is not None else (int(x // ROOM_SIZE), int(y // ROOM_SIZE))
        self.bounces = 0 # New: support bouncing
        
        # Visual based on bullet type
        if bullet_type == "rocket":
            # Large rocket appearance
            self.image = pygame.Surface((24, 12), pygame.SRCALPHA)
            pygame.draw.ellipse(self.image, (200, 50, 0), (0, 0, 24, 12))  # Red-orange rocket body
            pygame.draw.circle(self.image, YELLOW, (20, 6), 4)  # Flame at back
            self.image = pygame.transform.rotate(self.image, angle)
            self.explosion_radius = 100  # Damage radius
        elif bullet_type == "sniper":
            # Long, thin tracer bullet
            self.image = pygame.Surface((30, 3), pygame.SRCALPHA)
            pygame.draw.rect(self.image, CYAN, (0, 0, 30, 3))  # Cyan tracer
            pygame.draw.rect(self.image, WHITE, (25, 0, 5, 3))  # White tip
            self.image = pygame.transform.rotate(self.image, angle)
        elif bullet_type == "laser":
            # Thin, bright laser bolt
            self.image = pygame.Surface((20, 2), pygame.SRCALPHA)
            pygame.draw.rect(self.image, (255, 50, 50), (0, 0, 20, 2))
            pygame.draw.rect(self.image, WHITE, (15, 0, 5, 2))
            self.image = pygame.transform.rotate(self.image, angle)
        elif bullet_type == "grenade":
            # Small green-ish explosive
            self.image = pygame.Surface((14, 14), pygame.SRCALPHA)
            pygame.draw.circle(self.image, (50, 150, 50), (7, 7), 7)
            pygame.draw.circle(self.image, YELLOW, (7, 7), 3)
            self.explosion_radius = 70
        elif bullet_type == "heal":
            # Glowing green orb
            self.image = pygame.Surface((16, 16), pygame.SRCALPHA)
            pygame.draw.circle(self.image, (0, 255, 100), (8, 8), 8)
            pygame.draw.circle(self.image, WHITE, (8, 8), 4)
            self.image.set_alpha(200)
        else:
            # Normal bullet
            self.image = pygame.Surface((12, 4), pygame.SRCALPHA)
            self.image.fill(self.color)
            self.image = pygame.transform.rotate(self.image, angle)
        
        self.rect = self.image.get_rect(center=self.pos)

    def update(self):
        if self.exploded:
            self.explosion_timer -= 1
            return
        self.pos += self.velocity
        self.rect.center = self.pos
        self.lifetime -= 1

    def explode(self):
        """Trigger explosion for rockets and grenades."""
        if self.bullet_type in ["rocket", "grenade", "heal"] and not self.exploded:
            self.exploded = True
            self.explosion_timer = 15  # Show explosion for 15 frames
            # Create explosion particles
            if self.bullet_type == "rocket": color = ORANGE 
            elif self.bullet_type == "heal": color = (0, 255, 100)
            else: color = (100, 255, 100)
            create_particles(self.pos, 30, color, 3, 8, 15, 40)
            return True
        return False

    def draw(self, surface, camera_offset):
        draw_rect = self.rect.move(-camera_offset.x, -camera_offset.y)
        if self.exploded:
            # Draw explosion circle
            alpha = int(200 * (self.explosion_timer / 15))
            color = ORANGE if self.bullet_type == "rocket" else (50, 200, 50)
            inner_color = YELLOW if self.bullet_type == "rocket" else (150, 255, 150)
            explosion_surf = pygame.Surface((self.explosion_radius * 2, self.explosion_radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(explosion_surf, (*color, alpha), (self.explosion_radius, self.explosion_radius), self.explosion_radius)
            pygame.draw.circle(explosion_surf, (*inner_color, alpha), (self.explosion_radius, self.explosion_radius), self.explosion_radius // 2)
            surface.blit(explosion_surf, (draw_rect.centerx - self.explosion_radius, draw_rect.centery - self.explosion_radius))
        else:
            surface.blit(self.image, draw_rect)

class Weapon:
    def __init__(self, name, cooldown, damage, speed, count=1, spread=0, burst_count=1, burst_delay=0, min_click_delay=0):
        self.name = name
        self.cooldown = cooldown  # Frames between shots/bursts
        self.damage = damage
        self.speed = speed
        self.count = count  # Bullets per shot
        self.spread = spread
        self.last_shot_time = 0
        self.burst_count = burst_count  # Bullets per burst
        self.burst_delay = burst_delay  # Frames between burst bullets
        self.current_burst = 0
        self.burst_timer = 0
        self.min_click_delay = min_click_delay  # Anti-autoclicker (frames)
        self.last_click_time = 0

    def get_current_cooldown(self):
        return self.cooldown

    def can_shoot(self, current_time):
        return current_time - self.last_shot_time >= self.get_current_cooldown()

    def shoot(self, x, y, angle, current_time):
        self.last_shot_time = current_time
        bullets_data = []
        for i in range(self.count):
            actual_angle = angle + random.uniform(-self.spread, self.spread)
            bullets_data.append({
                "x": x, "y": y, 
                "angle": actual_angle, 
                "speed": self.speed,
                "damage": self.damage
            })
        if self.name == "Minigun":
            self.current_heat += 3.5
            if self.current_heat >= self.max_heat:
                self.overheated = True
                self.current_heat = self.max_heat
        return bullets_data

    def update(self):
        pass

class Pistol(Weapon):
    def __init__(self):
        # min_click_delay=10 = ~166ms at 60fps (anti-autoclicker)
        super().__init__("Pistol", 8, 10, 10, count=1, spread=2, min_click_delay=10)

class Uzi(Weapon):
    def __init__(self):
        # Burst fire: 3 bullets per burst, 0.7s (42 frames) cooldown between bursts
        # Added min_click_delay=15 to prevent spamming
        # Damage halved to 2.5
        super().__init__("Uzi", 42, 5, 18, count=1, spread=10, burst_count=3, burst_delay=3, min_click_delay=15)

class Shotgun(Weapon):
    def __init__(self):
        super().__init__("Shotgun", 60, 8, 12, count=5, spread=15)

class SniperRifle(Weapon):
    def __init__(self):
        # High damage (Reverted to 75), slow fire rate, no spread
        super().__init__("SniperRifle", 60, 75, 25, count=1, spread=0)

class Minigun(Weapon):
    def __init__(self):
        # Fast fire rate (2), low damage, high spread
        # Damage halved to 1.5
        super().__init__("Minigun", 2, 2.5, 15, count=1, spread=8)
        self.max_heat = 100
        self.current_heat = 0
        self.cooldown_rate = 1 # ~7 seconds to cool from 100
        self.overheated = False

    def get_current_cooldown(self):
        # Normal operation: Fast fire
        if not self.overheated:
            return self.cooldown
        
        # Overheated: Slow down significantly but don't stop
        # Fixed slow fire rate while cooling
        return 20 # 20 frames = ~0.33s delay (vs 2 frames normally)

    def can_shoot(self, current_time):
        # Allow shooting correctly utilizing the dynamic cooldown even if overheated
        return current_time - self.last_shot_time >= self.get_current_cooldown()

    def update(self):
        if self.current_heat > 0:
            self.current_heat -= self.cooldown_rate
            if self.current_heat < 0: self.current_heat = 0
        
        if self.overheated and self.current_heat == 0:
            self.overheated = False

class RocketLauncher(Weapon):
    def __init__(self):
        # Slow, high damage, explosive (handled in bullet collision)
        # Cooldown reduced to 0.8x (was 120, now 96)
        super().__init__("Rocket", 96, 50, 6, count=1, spread=0)

class LaserRifle(Weapon):
    def __init__(self):
        # Fast, accurate, medium damage
        super().__init__("LaserRifle", 15, 12, 20, count=1, spread=2)

class GrenadeLauncher(Weapon):
    def __init__(self):
        # Arcing projectiles (simulated by speed/drag?), explosive
        # Halved damage (was 40, now 20) and radius (handled via btype="grenade")
        super().__init__("GrenadeLauncher", 45, 30, 10, count=1, spread=5)

class DualPistols(Weapon):
    def __init__(self):
        # Very fast, low damage, dual shot (simulated by count=2 or just fast fire)
        # Let's do count=2 with spread
        super().__init__("DualPistols", 12, 6, 12, count=2, spread=10)

class DroppedWeapon:
    def __init__(self, id, weapon_class_name, x, y, cooldown=0):
        self.id = id
        self.weapon_class_name = weapon_class_name
        self.pos = pygame.math.Vector2(x, y)
        self.pickup_cooldown = cooldown # Frames before can be picked up
        
        # Visuals
        self.rect = pygame.Rect(x-15, y-15, 30, 30)
        self.color = GOLD if weapon_class_name in ["SniperRifle", "Rocket"] else SILVER
        self.hover_offset = 0
    
    def update(self):
        if self.pickup_cooldown > 0:
            self.pickup_cooldown -= 1
        
        # Simple hover animation
        self.hover_offset = math.sin(pygame.time.get_ticks() * 0.005) * 5
        self.rect.centery = self.pos.y + self.hover_offset
    
    def draw(self, surface, camera_offset, font):
        draw_rect = self.rect.move(-camera_offset.x, -camera_offset.y)
        pygame.draw.rect(surface, self.color, draw_rect, border_radius=5)
        
        # Letter Logic
        letter = "?"
        if self.weapon_class_name == "Pistol": letter = "P"
        elif self.weapon_class_name == "Uzi": letter = "U"
        elif self.weapon_class_name == "Shotgun": letter = "S"
        elif self.weapon_class_name == "SniperRifle": letter = "Sn"
        elif self.weapon_class_name == "Minigun": letter = "M"
        elif self.weapon_class_name in ["Rocket", "RocketLauncher"]: letter = "R"
        
        # Render Text
        text_surf = font.render(letter, True, BLACK)
        text_rect = text_surf.get_rect(center=draw_rect.center)
        surface.blit(text_surf, text_rect)

class HealPickup:
    def __init__(self, hid, x, y, amount=1, room_coords=None):
        self.id = hid
        self.pos = pygame.math.Vector2(x, y)
        self.amount = amount
        self.room_coords = room_coords if room_coords is not None else (int(x // ROOM_SIZE), int(y // ROOM_SIZE))
        self.rect = pygame.Rect(x - 14, y - 14, 28, 28)
        self.pulse = 0

    def update(self):
        self.pulse += 1
        self.rect.center = (int(self.pos.x), int(self.pos.y))

    def draw(self, surface, camera_offset, font):
        draw_rect = self.rect.move(-camera_offset.x, -camera_offset.y)
        r = 14 + int(math.sin(self.pulse * 0.12) * 2)
        center = draw_rect.center
        pygame.draw.circle(surface, (20, 80, 20), center, r)
        pygame.draw.circle(surface, (60, 200, 60), center, r, 3)
        pygame.draw.rect(surface, (240, 240, 240), (center[0] - 3, center[1] - 8, 6, 16))
        pygame.draw.rect(surface, (240, 240, 240), (center[0] - 8, center[1] - 3, 16, 6))

class Enemy:
    # Ported from Arow.py with all enemy types
    ENEMY_TYPES = {
        "charger": {"size": 32, "color": (255, 50, 50), "speed": 1.7, "hp": 20},
        "shooter": {"size": 28, "color": (255, 165, 0), "speed": 1.0, "hp": 20},
        "sniper": {"size": 30, "color": (180, 0, 255), "speed": 0.7, "hp": 20},
        "tank": {"size": 50, "color": (50, 100, 50), "speed": 0.5, "hp": 35},
        "kamikaze": {"size": 25, "color": (255, 100, 100), "speed": 2.8, "hp": 10},
        "turret": {"size": 40, "color": (100, 100, 100), "speed": 0, "hp": 20},
        "splitter": {"size": 35, "color": (0, 255, 200), "speed": 1.2, "hp": 10},
        # NEW ENEMIES (introduced progressively floor 3-7)
        "teleporter": {"size": 28, "color": (100, 0, 180), "speed": 0.8, "hp": 15},  # Floor 3+: Teleports periodically
        "shielder": {"size": 38, "color": (80, 80, 200), "speed": 0.9, "hp": 30},    # Floor 4+: Has frontal shield
        "dodger": {"size": 30, "color": (150, 255, 150), "speed": 1.5, "hp": 20},    # Floor 5+: Dodges bullets, predictive aim
        "healer": {"size": 26, "color": (0, 200, 100), "speed": 1.0, "hp": 12},      # Floor 6+: Heals nearby enemies
        "phaser": {"size": 32, "color": (150, 150, 200), "speed": 1.4, "hp": 20},    # Floor 7+: Phases in/out
    }
    
    def __init__(self, eid, x, y, type="charger", room_coords=None, lifespan=None):
        self.eid = eid
        self.type = type
        self.room_coords = room_coords
        self.pos = pygame.math.Vector2(x, y)
        self.lifespan = lifespan # Optional lifespan in frames
        
        # Get type-specific stats
        stats = self.ENEMY_TYPES.get(type, self.ENEMY_TYPES["charger"])
        self.size = stats["size"]
        self.color = stats["color"]
        self.speed = stats["speed"]
        self.hp = stats["hp"]
        
        # Generate Sprite (Ported from Arow.py)
        self.image = pygame.Surface((self.size, self.size), pygame.SRCALPHA)
        if type == "turret":
            pygame.draw.rect(self.image, self.color, (0, 0, self.size, self.size), border_radius=5)
            pygame.draw.circle(self.image, (200, 50, 50), (self.size//2, self.size//2), self.size//4)
        else:
            pygame.draw.circle(self.image, self.color, (self.size // 2, self.size // 2), self.size // 2)
            pygame.draw.circle(self.image, (0, 0, 0), (self.size // 2, self.size // 2), self.size // 4)
        
        self.rect = self.image.get_rect(center=(x, y))
        
        # Shooting timers
        self.last_shot = 0
        if type == "shooter":
            self.shoot_cooldown = 150
        elif type == "tank":
            self.shoot_cooldown = 200
        elif type == "turret":
            self.shoot_cooldown = 90
        elif type == "sniper":
            self.shoot_cooldown = 120
            self.state = "roaming"
            self.aim_timer = 0
            self.aim_duration = 120
        elif type == "teleporter":
            self.shoot_cooldown = 150
            self.teleport_timer = 180
            self.teleport_delay = 0
        elif type == "shielder":
            self.shoot_cooldown = 180
            self.shield_angle = 0
            self.shield_target_angle = 0
            self.shield_rotation_speed = 2.0 # Degrees per frame
            self.shield_active = True
        elif type == "dodger":
            self.shoot_cooldown = 120
            self.dodge_timer = 0
            self.dodge_direction = pygame.math.Vector2(0, 0)
        elif type == "healer":
            self.shoot_cooldown = 300 # Heals less often
            self.heal_range = 250
        elif type == "phaser":
            self.shoot_cooldown = 100
            self.phase_timer = 0
            self.is_phased = False # If true, invisible/invulnerable
        else:
            self.shoot_cooldown = 120
    
    def update_host(self, players, dungeon, network, game_bullets, game=None):
        # Lifespan Check
        if self.lifespan is not None:
            self.lifespan -= 1
            if self.lifespan <= 0:
                self.hp = 0 # Mark for death
                return

        # Check if frozen (activation delay)
        if hasattr(self, 'frozen') and self.frozen:
            return
        
        # Find closest valid target (alive and in same room)
        target = None
        min_dist = 9999
        for p in players.values():
            if not getattr(p, "alive", True):
                continue
            # Only target/attack players in the same room
            if getattr(p, "current_room_coords", None) is not None and self.room_coords is not None:
                if p.current_room_coords != self.room_coords:
                    continue
            dist = self.pos.distance_to(p.rect.center)
            if dist < min_dist:
                min_dist = dist
                target = p

        if not target:
            return
        
        direction = pygame.math.Vector2(target.rect.center) - self.pos
        dist = direction.length()
        if dist == 0: return
        
        if dist == 0: return
        
        # Calculate movement vector
        move_vec = direction.normalize() * self.speed
        new_pos = self.pos + move_vec
        
        # Wall Collision Check
        if self.room_coords in dungeon:
            room = dungeon[self.room_coords]
            walls = room.get_walls()
            # If room not cleared, doors are walls
            if not room.cleared:
                walls.extend(room.get_doors())
                
            # X Axis
            test_rect = self.rect.copy()
            test_rect.centerx = new_pos.x
            test_rect.centery = self.pos.y
            if test_rect.collidelist(walls) != -1:
                move_vec.x = 0
                
            # Y Axis
            test_rect = self.rect.copy()
            test_rect.centerx = self.pos.x + move_vec.x
            test_rect.centery = new_pos.y
            if test_rect.collidelist(walls) != -1:
                move_vec.y = 0
                
        # Apply movement
        self.pos += move_vec
        
        # AI by type
        if self.type == "charger":
             # Already moved
             pass
            
        elif self.type == "kamikaze":
            # Already moved (movement logic is shared above now)
            pass
            # Explode on contact is handled in collision
            
        elif self.type == "shooter":
            desired_dist = 400
            final_move = pygame.math.Vector2(0, 0)
            # Shoot at player
            if self.last_shot <= 0:
                angle = math.degrees(math.atan2(-direction.y, direction.x))
                bullet_id = f"enemy_{self.eid}_{pygame.time.get_ticks()}"
                network.send({"type": "SHOOT", "id": bullet_id, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle, "color": self.color, "speed": 7})
                game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle, bullet_id, 7, self.color))
                self.last_shot = self.shoot_cooldown
                final_move = direction.normalize() * self.speed
            elif dist < desired_dist - 50:
                final_move = -direction.normalize() * self.speed

            # Apply collision to final_move
            if self.room_coords in dungeon:
                # Reuse walls from above
                # X Axis
                test_rect = self.rect.copy()
                test_rect.centerx = self.pos.x + final_move.x
                test_rect.centery = self.pos.y
                if test_rect.collidelist(walls) != -1:
                    final_move.x = 0
                # Y Axis
                test_rect.centerx = self.pos.x + final_move.x
                test_rect.centery = self.pos.y + final_move.y
                if test_rect.collidelist(walls) != -1:
                    final_move.y = 0
            self.pos += final_move
                
        elif self.type == "tank":
            # Undo shared movement first
            self.pos -= move_vec
            
            if dist > 300:
                # Move towards
                final_move = direction.normalize() * self.speed
                # Collision
                if self.room_coords in dungeon:
                     test_rect = self.rect.copy()
                     test_rect.centerx = self.pos.x + final_move.x
                     test_rect.centery = self.pos.y
                     if test_rect.collidelist(walls) != -1: final_move.x = 0
                     test_rect.centerx = self.pos.x + final_move.x
                     test_rect.centery = self.pos.y + final_move.y
                     if test_rect.collidelist(walls) != -1: final_move.y = 0
                self.pos += final_move
            
            if self.last_shot <= 0:
                angle = math.degrees(math.atan2(-direction.y, direction.x))
                bullet_id = f"enemy_{self.eid}"
                for offset in [-15, 0, 15]:
                    network.send({"type": "SHOOT", "id": bullet_id, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle + offset, "color": self.color, "speed": 7})
                    game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle + offset, bullet_id, 7, self.color))
                self.last_shot = self.shoot_cooldown
                
        elif self.type == "turret":
            # Stationary, shoots at player
            if dist < 600 and self.last_shot <= 0:
                angle = math.degrees(math.atan2(-direction.y, direction.x))
                bullet_id = f"enemy_{self.eid}"
                for offset in [-10, 0, 10]:
                    network.send({"type": "SHOOT", "id": bullet_id, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle + offset, "color": self.color, "speed": 6})
                    game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle + offset, bullet_id, 6, self.color))
                self.last_shot = self.shoot_cooldown
                
        elif self.type == "splitter":
             # Shared movement applies
             pass
            
        elif self.type == "sniper":
            # Sniper with beam attack (Ported from Arow.py)
            if not hasattr(self, 'sniper_state'): 
                self.sniper_state = "roaming"
                self.aim_timer = 0
                self.locked_target_pos = None
                
            if self.sniper_state == "roaming":
                # Undo shared movement
                self.pos -= move_vec
                
                # Sniper moves slower (speed * 0.5)
                if dist > 0:
                    final_move = direction.normalize() * (self.speed * 0.5)
                    # Collision
                    if self.room_coords in dungeon:
                         test_rect = self.rect.copy()
                         test_rect.centerx = self.pos.x + final_move.x
                         test_rect.centery = self.pos.y
                         if test_rect.collidelist(walls) != -1: final_move.x = 0
                         test_rect.centerx = self.pos.x + final_move.x
                         test_rect.centery = self.pos.y + final_move.y
                         if test_rect.collidelist(walls) != -1: final_move.y = 0
                    self.pos += final_move
                
                if dist < 900: 
                    self.sniper_state = "aiming"
                    self.aim_timer = 120
            elif self.sniper_state == "aiming":
                self.aim_timer -= 1
                # Show laser target during aiming
                self.laser_target = target.rect.center
                if self.aim_timer <= 0: 
                    self.locked_target_pos = target.rect.center
                    self.sniper_state = "warning"
                    self.warn_timer = 60
            elif self.sniper_state == "warning":
                self.warn_timer -= 1
                # Keep laser visible during warning
                if self.locked_target_pos:
                    self.laser_target = self.locked_target_pos
                if self.warn_timer <= 0:
                    if self.locked_target_pos:
                        create_particles(self.rect.center, 40, PURPLE, 2, 7, 15, 30)
                        beam_dir = pygame.math.Vector2(self.locked_target_pos) - self.pos
                        if beam_dir.length() > 0:
                            angle = math.degrees(math.atan2(-beam_dir.y, beam_dir.x))
                            # Beam starts from sniper position
                            beam_pos = self.pos
                            # Store beam for game to track
                            self.pending_beam = {"pos": beam_pos, "angle": angle}
                            network.send({"type": "BEAM", "x": beam_pos.x, "y": beam_pos.y, "angle": angle})
                    self.sniper_state = "cooldown"
                    self.cooldown_timer = 120
                    self.laser_target = None
            elif self.sniper_state == "cooldown":
                self.cooldown_timer -= 1
                if self.cooldown_timer <= 0: 
                    self.sniper_state = "roaming"

        elif self.type == "teleporter":
            # Teleports periodically
            self.teleport_timer -= 1
            if self.teleport_timer <= 0:
                # Teleport!
                if self.room_coords in dungeon:
                    room = dungeon[self.room_coords]
                    rect = room.get_world_rect()
                    # Try to find a spot away from player
                    for _ in range(10):
                        tx = random.randint(rect.left + 100, rect.right - 100)
                        ty = random.randint(rect.top + 100, rect.bottom - 100)
                        tpos = pygame.math.Vector2(tx, ty)
                        if tpos.distance_to(target.rect.center) > 300:
                            create_particles(self.rect.center, 20, self.color, 2, 5, 10, 30)
                            self.pos = tpos
                            create_particles(self.rect.center, 20, self.color, 2, 5, 10, 30)
                            network.send({"type": "ENEMY_TELEPORT", "id": self.eid, "x": tx, "y": ty})
                            self.teleport_timer = 180 + random.randint(-60, 60)
                            break
            
            # Shoot occasionally
            if self.last_shot <= 0:
                angle = math.degrees(math.atan2(-direction.y, direction.x))
                bullet_id = f"enemy_{self.eid}_{pygame.time.get_ticks()}"
                network.send({"type": "SHOOT", "id": bullet_id, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle, "color": self.color, "speed": 6})
                game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle, bullet_id, 6, self.color))
                self.last_shot = self.shoot_cooldown

        elif self.type == "shielder":
            # Moves towards player, shield faces player (with delay)
            # Smoothly rotate shield_angle (independent of player)
            # Face the player smoothly: compute target angle toward player and rotate shield toward it
            # Shielder does not shoot — it is a defensive unit. Shield angle now protects front cone.
            # Rotate shield continuously around the enemy
            self.shield_angle = (self.shield_angle + self.shield_rotation_speed) % 360

            # Shielder does not shoot — it is a defensive unit. Shield angle now protects front cone.

        elif self.type == "dodger":
            # Complex AI: Dodges bullets and predictive aim
            # 1. Dodging
            dodge_vec = pygame.math.Vector2(0, 0)
            for b in game_bullets:
                if b.owner_id != self.eid and not b.owner_id.startswith("enemy"):
                    # Check if bullet is in same room
                    b_room = (int(b.pos.x // ROOM_SIZE), int(b.pos.y // ROOM_SIZE))
                    if b_room == self.room_coords:
                        dist_to_b = self.pos.distance_to(b.pos)
                        if dist_to_b < 150:
                            # Check if bullet is moving towards us
                            # Vector from bullet to us
                            to_us = self.pos - b.pos
                            if b.velocity.length() > 0:
                                dot = b.velocity.normalize().dot(to_us.normalize())
                                if dot > 0.8: # Bullet is heading roughly towards us
                                    # 66% chance to attempt a dodge (nerf: not perfect evasion)
                                    if random.random() < 0.66:
                                        # Move perpendicular to bullet velocity
                                        perp = pygame.math.Vector2(-b.velocity.y, b.velocity.x).normalize()
                                        # Choose direction that moves us further from bullet path or just random
                                        dodge_vec += perp * 2.5
            
            # Add error chance (mistakes)
            if random.random() < 0.05: # 5% chance per frame to stop dodging or move randomly
                 dodge_vec = pygame.math.Vector2(random.uniform(-1, 1), random.uniform(-1, 1)).normalize() * 2
            
            if dodge_vec.length() > 0:
                # Apply dodge movement with wall collision
                if self.room_coords in dungeon:
                    test_rect = self.rect.copy()
                    test_rect.centerx = self.pos.x + dodge_vec.x
                    test_rect.centery = self.pos.y
                    if test_rect.collidelist(walls) != -1: dodge_vec.x = 0
                    test_rect.centerx = self.pos.x + dodge_vec.x
                    test_rect.centery = self.pos.y + dodge_vec.y
                    if test_rect.collidelist(walls) != -1: dodge_vec.y = 0
                self.pos += dodge_vec
            
            # 2. Predictive Aim
            if self.last_shot <= 0:
                # Estimate where player will be: target_pos + target_vel * (dist / bullet_speed)
                bullet_speed = 8
                time_to_hit = dist / bullet_speed
                
                target_vel = getattr(target, 'velocity', pygame.math.Vector2(0, 0))
                predicted_pos = pygame.math.Vector2(target.rect.center) + target_vel * time_to_hit
                
                # Aim at predicted position
                aim_dir = predicted_pos - self.pos
                if aim_dir.length() > 0:
                    angle = math.degrees(math.atan2(-aim_dir.y, aim_dir.x))
                else:
                    angle = math.degrees(math.atan2(-direction.y, direction.x))
                    
                bullet_id = f"enemy_{self.eid}_{pygame.time.get_ticks()}"
                network.send({"type": "SHOOT", "id": bullet_id, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle, "color": self.color, "speed": bullet_speed})
                game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle, bullet_id, bullet_speed, self.color))
                self.last_shot = self.shoot_cooldown

        elif self.type == "healer":
            # Undo shared movement
            self.pos -= move_vec
            
            # Find injured ally (enemy or boss)
            heal_target = None
            if game:
                # Check regular enemies
                for eid, e in game.enemies.items():
                    if e.room_coords == self.room_coords and e.eid != self.eid:
                        stats = self.ENEMY_TYPES.get(e.type, self.ENEMY_TYPES["charger"])
                        max_hp = stats["hp"] + (getattr(game, 'floor_number', 1) // 3)
                        if e.hp < max_hp:
                            heal_target = e
                            break
                
                # Check bosses if no regular enemy needs healing or just check both
                if not heal_target:
                    for bid, b_obj in game.bosses.items():
                        if b_obj.room_coords == self.room_coords and b_obj.hp < b_obj.max_hp:
                            heal_target = b_obj
                            break
            
            final_move = pygame.math.Vector2(0,0)
            if heal_target:
                heal_dir = heal_target.pos - self.pos
                if heal_dir.length() > 100:
                    final_move = heal_dir.normalize() * self.speed
            else:
                # Avoid player
                if dist < 400:
                    final_move = -direction.normalize() * self.speed
            
            # Apply collision
            if self.room_coords in dungeon:
                 test_rect = self.rect.copy()
                 test_rect.centerx = self.pos.x + final_move.x
                 test_rect.centery = self.pos.y
                 if test_rect.collidelist(walls) != -1: final_move.x = 0
                 test_rect.centerx = self.pos.x + final_move.x
                 test_rect.centery = self.pos.y + final_move.y
                 if test_rect.collidelist(walls) != -1: final_move.y = 0
            self.pos += final_move

            # Heal Pulse
            if self.last_shot <= 0:
                # Heal all enemies in range
                create_particles(self.rect.center, 30, (0, 255, 100), 2, 5, 10, 30)
                # Logic to actually heal would need access to game.enemies properly
                # For now, visual only + maybe spawn a "healing projectile" that seeks enemies?
                # Let's just spawn a healing projectile at nearest enemy
                if heal_target:
                    angle = math.degrees(math.atan2(-(heal_target.pos.y - self.pos.y), heal_target.pos.x - self.pos.x))
                    bullet_id = f"enemy_{self.eid}_{pygame.time.get_ticks()}"
                    # Green healing orb - faster (speed 12)
                    game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle, bullet_id, 12, (0, 255, 0), bullet_type="heal"))
                    network.send({"type": "SHOOT", "id": bullet_id, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle, "color": (0, 255, 0), "speed": 12, "btype": "heal"})
                self.last_shot = self.shoot_cooldown

        elif self.type == "phaser":
            # Phases in and out
            self.phase_timer += 1
            if self.phase_timer > 120:
                self.is_phased = not self.is_phased
                self.phase_timer = 0
                # Send update? Visuals will handle it based on is_phased
            
            # Move erratically?
            # Already moving towards player via shared logic
            
            if not self.is_phased and self.last_shot <= 0:
                angle = math.degrees(math.atan2(-direction.y, direction.x))
                bullet_id = f"enemy_{self.eid}_{pygame.time.get_ticks()}"
                network.send({"type": "SHOOT", "id": bullet_id, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle, "color": self.color, "speed": 10}) # Fast shot
                game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle, bullet_id, 10, self.color))
                self.last_shot = self.shoot_cooldown
            
        if self.last_shot > 0: self.last_shot -= 1
        self.rect.center = self.pos

    def draw(self, surface, camera_offset):
        if self.type == "phaser" and getattr(self, "is_phased", False):
            # Draw semi-transparent or just skip? 
            # Let's draw a faint outline
            draw_rect = self.rect.move(-camera_offset.x, -camera_offset.y)
            pygame.draw.circle(surface, (*self.color, 100), draw_rect.center, self.size // 2, 1)
            return

        draw_rect = self.rect.move(-camera_offset.x, -camera_offset.y)
        surface.blit(self.image, draw_rect)
        
        # Draw shielder's shield
        if self.type == "shielder":
            # Draw an arc or line in front
            shield_surf = pygame.Surface((self.size * 2, self.size * 2), pygame.SRCALPHA)
            # Draw arc
            start_angle = math.radians(-self.shield_angle - 45)
            end_angle = math.radians(-self.shield_angle + 45)
            pygame.draw.arc(shield_surf, (100, 100, 255), (0, 0, self.size * 2, self.size * 2), min(start_angle, end_angle), max(start_angle, end_angle), 5)
            surface.blit(shield_surf, (draw_rect.centerx - self.size, draw_rect.centery - self.size))

        # Draw healer pulse
        if self.type == "healer":
            pulse = (math.sin(pygame.time.get_ticks() * 0.01) + 1) * 0.5
            pygame.draw.circle(surface, (0, 255, 100, 100), draw_rect.center, self.size + pulse * 10, 2)

        # Draw sniper laser line during aiming/warning
        if self.type == "sniper" and hasattr(self, 'laser_target') and self.laser_target:
            start_pos = (self.rect.centerx - camera_offset.x, self.rect.centery - camera_offset.y)
            end_pos = (self.laser_target[0] - camera_offset.x, self.laser_target[1] - camera_offset.y)
            # Pulsing red laser line
            pygame.draw.line(surface, (255, 0, 0), start_pos, end_pos, 2)

# --- Boss Class (Ported from Arow.py) ---
class Boss:
    VARIANTS = ["standard", "summoner", "rusher", "orbweaver"]
    
    def __init__(self, bid, x, y, room_coords=None, variant=None):
        self.bid = bid
        self.room_coords = room_coords
        self.pos = pygame.math.Vector2(x, y)
        self.variant = variant if variant else random.choice(self.VARIANTS)
        
        # Create sprite
        self.image = pygame.Surface((100, 100), pygame.SRCALPHA)
        if self.variant == "summoner":
            self.color = (138, 43, 226) # Blue Violet
            pygame.draw.polygon(self.image, self.color, [(50, 0), (100, 50), (50, 100), (0, 50)])
            pygame.draw.circle(self.image, WHITE, (50, 50), 20)
        elif self.variant == "orbweaver":
            self.color = ORANGE
            pygame.draw.circle(self.image, self.color, (50, 50), 48)
            pygame.draw.circle(self.image, YELLOW, (50, 50), 10)
        elif self.variant == "rusher":
            self.color = (255, 69, 0) # Red Orange
            pygame.draw.polygon(self.image, self.color, [(0, 0), (100, 0), (50, 100)])
            pygame.draw.circle(self.image, YELLOW, (50, 30), 10)
        else: # standard
            self.color = (200, 0, 0)
            pygame.draw.rect(self.image, self.color, self.image.get_rect(), border_radius=15)
            pygame.draw.circle(self.image, YELLOW, (50, 50), 20)
        
        self.rect = self.image.get_rect(center=(x, y))
        self.hp = 495  # 1.5x increase from 330
        self.max_hp = 495
        self.speed = 0.7
        self.stage = 1
        self.action_timer = 0
        self.shoot_cooldown = 140
        self.shoot_timer = 0
        self.is_rushing = False
        self.rush_target = None
        self.minion_ids = []

        # Standard boss laser attack state (multi-target)
        self.laser_state = "idle"  # idle, aiming, warning, cooldown
        self.laser_targets = {}  # pid: (x, y)
        self.locked_targets = {} # pid: (x, y)
        self._laser_timer = 0
        self._laser_cooldown_timer = 0
        self._last_player_positions = {} # pid: Vector2
        self._player_vels = {} # pid: Vector2
        self._standard_shot_count = 0
        self._orbweaver_rotation = random.uniform(0, 360)
        self._orbweaver_shockwave_cd = 240
        self._last_target_pos = None  # For predictive attacks
        self._target_vel = pygame.math.Vector2(0, 0)
    
    def update_host(self, players, dungeon, network, game_bullets, game):
        # Update Stage
        health_ratio = self.hp / self.max_hp
        self.stage = 3 if health_ratio < 0.33 else (2 if health_ratio < 0.66 else 1)

        # Find closest valid target (alive and in same room)
        target = None
        min_dist = 9999
        for p in players.values():
            if not getattr(p, "alive", True):
                continue
            if getattr(p, "current_room_coords", None) is not None and self.room_coords is not None:
                if p.current_room_coords != self.room_coords:
                    continue
            dist = self.pos.distance_to(p.rect.center)
            if dist < min_dist:
                min_dist = dist
                target = p

        if not target:
            return
        
        direction = pygame.math.Vector2(target.rect.center) - self.pos
        dist = direction.length()

        # Update target velocity estimate for predictive attacks
        curr_tpos = pygame.math.Vector2(target.rect.center)
        if self._last_target_pos is not None:
            self._target_vel = curr_tpos - self._last_target_pos
        self._last_target_pos = curr_tpos
        
        # Movement calculation
        move_vec = pygame.math.Vector2(0, 0)
        
        if self.variant == "rusher" and self.is_rushing:
             rush_dir = self.rush_target - self.pos
             if rush_dir.length() < 20 or self.action_timer % 200 > 60:
                 self.is_rushing = False
                 for i in range(24):
                     game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, i * 15, self.bid, 8, RED))
                     network.send({"type": "SHOOT", "id": self.bid, "x": self.rect.centerx, "y": self.rect.centery, "angle": i * 15, "color": RED, "speed": 8})
             else:
                 move_vec = rush_dir.normalize() * (self.speed * 5)
        else:
             if dist > 0:
                 move_vec = direction.normalize() * self.speed
        
        # Apply Wall Collision to move_vec
        if self.room_coords in dungeon:
            room = dungeon[self.room_coords]
            walls = room.get_walls()
            if not room.cleared: walls.extend(room.get_doors())
            
            test_rect = self.rect.copy()
            test_rect.centerx = self.pos.x + move_vec.x
            test_rect.centery = self.pos.y
            if test_rect.collidelist(walls) != -1: move_vec.x = 0
            
            test_rect.centerx = self.pos.x + move_vec.x
            test_rect.centery = self.pos.y + move_vec.y
            if test_rect.collidelist(walls) != -1: move_vec.y = 0
            
        self.pos += move_vec
        self.rect.center = self.pos
        self.action_timer += 1
        
        # Variant Logic
        if self.variant == "summoner":
            # Turrets
            if self.action_timer % 300 == 0:
                # Clean up list
                self.minion_ids = [mid for mid in self.minion_ids if mid in game.enemies]
                
                if len(self.minion_ids) < self.stage * 3:
                    for _ in range(self.stage):
                        ex = self.pos.x + random.randint(-200, 200)
                        ey = self.pos.y + random.randint(-200, 200)
                        # Pass lifespan=480 (8 seconds)
                        eid = game.spawn_enemy(ex, ey, "turret", self.room_coords, lifespan=480)
                        self.minion_ids.append(eid)
                        
            # Orbiting bullets
            if self.action_timer % 120 == 0:
                for i in range(8):
                    angle = i * 45 + self.action_timer
                    game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle, self.bid, 8, CYAN))
                    network.send({"type": "SHOOT", "id": self.bid, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle, "color": CYAN, "speed": 8})

        elif self.variant == "rusher":
            if not self.is_rushing and self.action_timer % 200 == 0:
                self.is_rushing = True
                self.rush_target = target.pos.copy() if hasattr(target, 'pos') else pygame.math.Vector2(target.rect.center)

        elif self.variant == "orbweaver":
            # Aggressiveness scales with stage
            # Stage 1: Slower movement, less frequent spiral
            # Stage 2: Normal movement, expansion rings added
            # Stage 3: Fast movement, bounced shots added, faster spiral
            
            # Adjust speed based on stage
            if self.stage == 1: self.speed = 0.5
            elif self.stage == 2: self.speed = 0.8
            else: self.speed = 1.2

            # Spiral Volley
            spiral_freq = 90 if self.stage == 1 else (60 if self.stage == 2 else 40)
            if self.action_timer % spiral_freq == 0:
                self._orbweaver_rotation = (self._orbweaver_rotation + (15 if self.stage == 1 else 25)) % 360
                base = self._orbweaver_rotation
                bullet_count = 6 if self.stage == 1 else (10 if self.stage == 2 else 14)
                for i in range(bullet_count):
                    ang = base + i * (360 / bullet_count)
                    game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, ang, self.bid, 7 if self.stage == 1 else 9, ORANGE))
                    network.send({"type": "SHOOT", "id": self.bid, "x": self.rect.centerx, "y": self.rect.centery, "angle": ang, "color": ORANGE, "speed": 7 if self.stage == 1 else 9})

            # Radial Pulse
            if self.action_timer % 300 == 0:
                # Slow pulse ring
                self._orbweaver_rotation = (self._orbweaver_rotation + 11) % 360
                pulse_count = 12 if self.stage == 1 else 16
                for i in range(pulse_count):
                    ang = self._orbweaver_rotation + i * (360 / pulse_count)
                    game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, ang, self.bid, 5, YELLOW))
                    network.send({"type": "SHOOT", "id": self.bid, "x": self.rect.centerx, "y": self.rect.centery, "angle": ang, "color": YELLOW, "speed": 5})

            # Shockwave knockback (push players away) - only stage 2+
            if self.stage >= 2:
                self._orbweaver_shockwave_cd -= 1
                if self._orbweaver_shockwave_cd <= 0:
                    self._orbweaver_shockwave_cd = 300
                    shock_radius = 120
                    max_push = 80
                    create_particles(self.rect.center, 120, YELLOW, 2, 9, 20, 50)

                    for pid, p in players.items():
                        if not getattr(p, "alive", True):
                            continue
                        if getattr(p, "current_room_coords", None) is not None and self.room_coords is not None:
                            if p.current_room_coords != self.room_coords:
                                continue

                        delta = pygame.math.Vector2(p.rect.center) - self.pos
                        dist = delta.length()
                        if dist <= 0 or dist > shock_radius:
                            continue

                        strength = max_push * (1 - (dist / shock_radius))
                        push = delta.normalize() * strength
                        new_center = (int(p.rect.centerx + push.x), int(p.rect.centery + push.y))
                        p.rect.center = new_center
                        p.current_room_coords = (int(p.rect.centerx // ROOM_SIZE), int(p.rect.centery // ROOM_SIZE))
                        network.send({"type": "PLAYER_KNOCKBACK", "id": pid, "pos": p.rect.center})

            # Expansion rings - only stage 2+
            if self.stage >= 2 and self.action_timer % 240 == 120:
                # Expansion Ring (fast expanding)
                ring_count = 15 if self.stage == 2 else 25
                for i in range(ring_count):
                    ang = i * (360 / ring_count) + self.action_timer
                    game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, ang, self.bid, 11, YELLOW))
                    network.send({"type": "SHOOT", "id": self.bid, "x": self.rect.centerx, "y": self.rect.centery, "angle": ang, "color": YELLOW, "speed": 11})
            
            # Bouncing Spores - only stage 3
            if self.stage >= 3 and self.action_timer % 360 == 180:
                 # Bouncing Spores
                 for p in players.values():
                     if getattr(p, "alive", True) and getattr(p, "current_room_coords", None) == self.room_coords:
                         target_pos = pygame.math.Vector2(p.rect.center)
                         dir_to_p = (target_pos - self.pos).normalize()
                         angle = math.degrees(math.atan2(-dir_to_p.y, dir_to_p.x))
                         for off in [-20, 0, 20]:
                             b = Bullet(self.rect.centerx, self.rect.centery, angle + off, self.bid, 7, GREEN)
                             b.bounces = 3
                             game_bullets.append(b)
                             network.send({"type": "SHOOT", "id": self.bid, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle+off, "color": GREEN, "speed": 7})

        else: # standard
            if self.action_timer % self.shoot_cooldown == 0:
                angle = math.degrees(math.atan2(-direction.y, direction.x))
                for i in range(-2, 3):
                    game_bullets.append(Bullet(self.rect.centerx, self.rect.centery, angle + i * 15, self.bid, 8, self.color))
                    network.send({"type": "SHOOT", "id": self.bid, "x": self.rect.centerx, "y": self.rect.centery, "angle": angle + i * 15, "color": self.color, "speed": 8})

                # Laser should happen after every 3 regular volleys
                self._standard_shot_count += 1
                if self._standard_shot_count % 3 == 0 and self.laser_state == "idle":
                    self.laser_state = "aiming"
                    self._laser_timer = 60
                    self.locked_targets = {}
                    self.laser_targets = {}

            # Multi-Target Laser Logic
            # Update player velocity estimates for all players in room
            for pid, p in players.items():
                if not getattr(p, "alive", True) or getattr(p, "current_room_coords", None) != self.room_coords:
                    if pid in self._last_player_positions: del self._last_player_positions[pid]
                    if pid in self._player_vels: del self._player_vels[pid]
                    continue
                
                curr_p_pos = pygame.math.Vector2(p.rect.center)
                if pid in self._last_player_positions:
                    self._player_vels[pid] = curr_p_pos - self._last_player_positions[pid]
                else:
                    self._player_vels[pid] = pygame.math.Vector2(0, 0)
                self._last_player_positions[pid] = curr_p_pos

            if self.laser_state == "aiming":
                self._laser_timer -= 1
                lead_frames = 20
                self.laser_targets = {}
                for pid, p in players.items():
                    if not getattr(p, "alive", True) or getattr(p, "current_room_coords", None) != self.room_coords:
                        continue
                    vel = self._player_vels.get(pid, pygame.math.Vector2(0, 0))
                    predicted = pygame.math.Vector2(p.rect.center) + (vel * lead_frames)
                    self.laser_targets[pid] = (int(predicted.x), int(predicted.y))
                
                if self._laser_timer <= 0:
                    self.locked_targets = self.laser_targets.copy()
                    self.laser_state = "warning"
                    self._laser_timer = 90

            elif self.laser_state == "warning":
                self._laser_timer -= 1
                self.laser_targets = self.locked_targets
                if self._laser_timer <= 0:
                    create_particles(self.rect.center, 60, PURPLE, 2, 7, 15, 30)
                    for pid, locked_pos in self.locked_targets.items():
                        beam_dir = pygame.math.Vector2(locked_pos) - self.pos
                        if beam_dir.length() > 0:
                            beam_angle = math.degrees(math.atan2(-beam_dir.y, beam_dir.x))
                            beam_pos = self.pos
                            game.beams.append(EnergyBeam(beam_pos, beam_angle))
                            network.send({"type": "BEAM", "x": beam_pos.x, "y": beam_pos.y, "angle": beam_angle})
                    self.laser_state = "cooldown"
                    self._laser_timer = 90
                    self.laser_targets = {}

            elif self.laser_state == "cooldown":
                self._laser_timer -= 1
                if self._laser_timer <= 0:
                    self.laser_state = "idle"
                    self.laser_targets = {}
    
    def draw(self, surface, camera_offset):
        draw_rect = self.rect.move(-camera_offset.x, -camera_offset.y)
        surface.blit(self.image, draw_rect)

        # Draw standard boss laser line during aiming/warning
        if self.variant == "standard" and getattr(self, 'laser_targets', {}):
            for pid, target_pos in self.laser_targets.items():
                start_pos = (self.rect.centerx - camera_offset.x, self.rect.centery - camera_offset.y)
                end_pos = (target_pos[0] - camera_offset.x, target_pos[1] - camera_offset.y)
                pygame.draw.line(surface, (255, 0, 0), start_pos, end_pos, 2)

        # Draw health bar
        bar_width = 80
        bar_height = 8
        health_pct = self.hp / self.max_hp
        pygame.draw.rect(surface, RED, (draw_rect.centerx - bar_width//2, draw_rect.top - 15, bar_width, bar_height))
        pygame.draw.rect(surface, GREEN, (draw_rect.centerx - bar_width//2, draw_rect.top - 15, int(bar_width * health_pct), bar_height))

# --- Entities ---
class Player:
    def __init__(self, pid, x, y, is_local=False):
        self.pid = pid
        self.is_local = is_local
        
        # Sprite Generation
        self.image_size = 30
        self.original_image = pygame.Surface((self.image_size, self.image_size), pygame.SRCALPHA)
        # Main Body
        pygame.draw.polygon(self.original_image, PLAYER_COLOR,
                            [(self.image_size, self.image_size / 2), (0, 0), (0, self.image_size)])
        # Cockpit/Detail
        pygame.draw.polygon(self.original_image, CYAN, [(self.image_size - 5, self.image_size / 2),
                                                        (self.image_size - 10, self.image_size / 2 - 5),
                                                        (self.image_size - 10, self.image_size / 2 + 5)])
        self.image = self.original_image
        self.rect = pygame.Rect(0, 0, self.image_size, self.image_size)
        self.rect.center = (x, y)
        self.collider_radius = self.image_size // 2 - 1
        self.angle = 0
        
        # Pre-rotate for performance
        self.rotated_images = {}
        for ang in range(360):
            rotated = pygame.transform.rotate(self.original_image, ang)
            self.rotated_images[ang] = rotated
            
        self.speed = 3.5 # Adjusted from 5 to match Arow
        self.current_room_coords = (0, 0) # Grid coordinates
        self.prev_pos = pygame.math.Vector2(x, y)
        self.velocity = pygame.math.Vector2(0, 0)
        
        # --- CHANGE START ---
        self.hp = 5
        self.max_hp = 5
        self.alive = True # Track if player is alive
        # --- CHANGE END ---
        
        # Dash ability (5 second cooldown = 300 frames at 60fps)
        self.dash_cooldown = 300  # 5 seconds
        self.dash_timer = 0  # Current cooldown timer (0 = ready)
        self.dash_speed = 15  # Speed multiplier during dash
        self.dash_duration = 8  # Frames of dash
        self.is_dashing = False
        self.dash_frames_left = 0
        self.dash_direction = (0, 0)  # Direction of dash
        
        self.weapon = Pistol()
        self.name = f"Player{pid}"
        self.name_color = WHITE

    def move(self, dx, dy, walls):
        center = pygame.math.Vector2(self.rect.center)
        center += pygame.math.Vector2(dx, dy) * self.speed
        for wall in walls:
            center = self._resolve_circle_rect(center, self.collider_radius, wall)
        self.prev_pos = pygame.math.Vector2(self.rect.center)
        self.rect.center = (center.x, center.y)
        self.velocity = (pygame.math.Vector2(self.rect.center) - self.prev_pos)
            
    def update_angle(self, camera_offset, walls=[]):
        mx, my = pygame.mouse.get_pos()
        # Mouse is screen space, player is world space => convert to same space
        # Screen space player pos:
        screen_player_x = self.rect.centerx - camera_offset.x
        screen_player_y = self.rect.centery - camera_offset.y
        
        rel_x, rel_y = mx - screen_player_x, my - screen_player_y
        angle = math.degrees(math.atan2(-rel_y, rel_x))
        self.angle = int(angle) % 360
        if self.angle < 0: self.angle += 360
        
        self.image = self.rotated_images[self.angle]
        old_center = self.rect.center
        self.rect = pygame.Rect(0, 0, self.image_size, self.image_size)
        self.rect.center = old_center

    def shoot_pos(self):
        # 30 size, center is 15. Tip is at 30.
        # Vector from center to tip
        vec = pygame.math.Vector2(self.image_size / 2, 0).rotate(-self.angle)
        return self.rect.center + vec
    
    def set_angle(self, angle):
        self.angle = int(angle) % 360
        if self.angle < 0: self.angle += 360
        self.image = self.rotated_images[self.angle]
        old_center = self.rect.center
        self.rect = pygame.Rect(0, 0, self.image_size, self.image_size)
        self.rect.center = old_center
    
    def _resolve_circle_rect(self, center, radius, rect):
        closest_x = max(rect.left, min(center.x, rect.right))
        closest_y = max(rect.top, min(center.y, rect.bottom))
        delta = pygame.math.Vector2(center.x - closest_x, center.y - closest_y)
        dist = delta.length()
        if dist == 0:
            overlaps = [
                (abs(center.x - rect.left), pygame.math.Vector2(-1, 0)),
                (abs(center.x - rect.right), pygame.math.Vector2(1, 0)),
                (abs(center.y - rect.top), pygame.math.Vector2(0, -1)),
                (abs(center.y - rect.bottom), pygame.math.Vector2(0, 1)),
            ]
            overlap_dir = min(overlaps, key=lambda v: v[0])[1]
            delta = overlap_dir
            dist = 0.0001
        if dist < radius:
            delta.normalize_ip()
            center += delta * (radius - dist)
        return center

    def draw(self, surface, camera_offset):
        if not getattr(self, "alive", True):
            return
        # Render image centered on collider to avoid pivot jitter
        image_rect = self.image.get_rect(center=self.rect.center)
        draw_rect = image_rect.move(-camera_offset.x, -camera_offset.y)
        surface.blit(self.image, draw_rect)

class Game:
    def __init__(self):
        pygame.init()
        # Start in fullscreen by default
        self.fullscreen = True
        self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption("Roomarow Multiplayer")
        try:
            icon_img = pygame.image.load(resource_path("icon.png")).convert_alpha()
            pygame.display.set_icon(icon_img)
        except Exception:
            pass
        self.clock = pygame.time.Clock()
        self.running = True
        self.state = "SPLASH" # SPLASH, MENU, LOBBY, GAME
        self.menu_screen = "MAIN"  # MAIN, MULTIPLAYER, SETTINGS
        self.network = NetworkManager()
        self.font = pygame.font.Font(None, 36)

        self.title_image = None
        self.title_image_scaled = None
        self.title_image_scaled_size = None
        try:
            self.title_image = pygame.image.load(resource_path("title.png")).convert_alpha()
        except Exception:
            self.title_image = None

        self.splash_start_time = pygame.time.get_ticks()
        self.splash_duration = 3000
        self.fade_in_duration = 500
        self.fade_out_duration = 500
        self.splash_image = None
        self.splash_rect = None
        try:
            splash_original = pygame.image.load(resource_path("calistasplash.png")).convert_alpha()
            ow, oh = splash_original.get_size()
            nw, nh = int(ow * 0.7), int(oh * 0.7)
            self.splash_image = pygame.transform.smoothscale(splash_original, (nw, nh))
            sw, sh = self.screen.get_size()
            self.splash_rect = self.splash_image.get_rect(center=(sw // 2, sh // 2))
        except Exception:
            self.state = "MENU"

        self.menu_stars = []
        self.star_speed = 15
        self.star_depth = 1000
        for _ in range(360):
            self.menu_stars.append({
                "x": random.randint(-2000, 2000),
                "y": random.randint(-2000, 2000),
                "z": random.randint(1, self.star_depth),
                "color": random.choice([
                    (255, 255, 255), (200, 200, 255), (220, 240, 255), (150, 200, 255)
                ]),
                "base_size": random.uniform(0.5, 2.0)
            })
        
        # Game State
        self.players = {} 
        self.local_id = str(random.randint(1000, 9999))
        self.name_colors = [WHITE, RED, GREEN, BLUE, YELLOW, ORANGE, CYAN, PURPLE, GOLD, (255, 105, 180)] # Adding Pink
        self.local_name_color = random.choice(self.name_colors)
        self.join_ip = ""
        
        # Persistent Settings
        self.data_dir = "data"
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
        self.settings_file = os.path.join(self.data_dir, "settings.json")
        self._load_settings()
        # Audio System
        self.sounds = {}
        self.current_music = None
        self.client_conns = {} # Map conn -> pid
        self._init_audio()
        self.dragging_game = False
        self.dragging_music = False
        # Now that sounds are loaded, update volumes
        self._update_audio_volumes()
        
        self.seed = None
        self.dungeon = None
        self.current_room_coords = (0,0)
        self.camera = pygame.math.Vector2(0,0)
        self.bullets = []
        self.dropped_weapons = []
        self.heal_pickups = []
        # Channels used for looping weapon sounds (keyed by player id)
        self.weapon_channels = {}
        self.beams = []  # EnergyBeams
        self.enemies = {}
        self.enemy_counter = 0
        self.bosses = {}  # Boss entities
        self.boss_counter = 0
        self.chests = []
        self.visited_rooms = set()
        self.minimap_visible = True
        self.shoot_pressed = False  # For click-to-shoot (gameplay)
        self.pause_menu_open = False
        self.pause_click_held = False  # Separate click handling for pause menu buttons
        self.name_input_active = False
        self.menu_click_held = False
        
        # --- ADD THESE ---
        self.spectating_id = None # ID of the player currently being spectated
        self.game_over = False
        # -----------------

        # Level progression
        self.floor_number = 1
        self.trapdoor = None  # Rect for trapdoor after boss death
        self.trapdoor_room = None  # Which room the trapdoor is in
        self.level_transition_pending = False
        self.level_transition_requester = None
        self.level_transition_accepted = set()  # Player IDs who accepted
        self.floor_color = BLACK
        
        # Audio System (moved above)
        
        # Boss kill counter for progressive difficulty (every 3rd boss gets +100 hp)
        self.boss_kills_total = 0
        self.last_boss_variant = None

    def _load_settings(self):
        import json
        self.local_name = f"Player{random.randint(100, 999)}"
        self.game_volume = 0.5
        self.music_volume = 0.5
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                    self.local_name = data.get("name", self.local_name)
                    self.game_volume = data.get("game_volume", 0.5)
                    self.music_volume = data.get("music_volume", 0.5)
                print(f"Loaded settings: name={self.local_name}, game_volume={self.game_volume}, music_volume={self.music_volume}")
            except Exception as e:
                print(f"Warning: Failed to load settings.json: {e}. Using defaults.")
        # (Audio volumes are updated after audio is initialized in __init__)

    def _save_settings(self):
        import json
        data = {
            "name": self.local_name,
            "game_volume": self.game_volume,
            "music_volume": self.music_volume
        }
        try:
            with open(self.settings_file, "w") as f:
                json.dump(data, f)
        except:
            pass

    def _init_audio(self):
        try:
            pygame.mixer.init()
            # Allow more simultaneous channels so rapid firing doesn't cut sounds off
            try:
                pygame.mixer.set_num_channels(64)
            except Exception:
                pass

            # Load sounds
            sounds_to_load = {
                "click": "sfx/click.mp3",
                "shot": "sfx/shot.mp3",
                "explosion": "sfx/explosion.mp3",
                "enemy_hit": "sfx/enemy_hit.mp3",
                "enemy_death": "sfx/enemy_death.mp3",
                "player_hit": "sfx/player_hit.mp3",
                "chest_open": "sfx/chest_open.mp3",
                "pickup": "sfx/pickup.mp3",
                "heal": "sfx/heal.mp3"
            }
            for name, path in sounds_to_load.items():
                full_path = resource_path(path)
                if os.path.exists(full_path):
                    self.sounds[name] = pygame.mixer.Sound(full_path)
                else:
                    # Generate synthetic sound if file missing
                    self.sounds[name] = self._generate_synthetic_sound(name)
            # Per-weapon sounds (optional). If present in sfx/, these override the generic shot.
            self.weapon_sounds = {}
            weapon_sound_names = ["Pistol", "Uzi", "Shotgun", "SniperRifle", "Minigun", "Rocket", "LaserRifle", "GrenadeLauncher", "DualPistols"]
            for wname in weapon_sound_names:
                # try lowercased filename first, then classname
                cand1 = resource_path(f"sfx/{wname.lower()}.mp3")
                cand2 = resource_path(f"sfx/{wname}.mp3")
                path = None
                if os.path.exists(cand1): path = cand1
                elif os.path.exists(cand2): path = cand2
                if path:
                    try:
                        self.weapon_sounds[wname] = pygame.mixer.Sound(path)
                    except Exception:
                        self.weapon_sounds[wname] = self._generate_synthetic_sound("shot")
                else:
                    # no specific weapon sound provided
                    self.weapon_sounds[wname] = None
        except Exception as e:
            print(f"Audio init error: {e}")

    def _generate_synthetic_sound(self, name):
        sample_rate = 44100
        duration = 0.1
        
        if name == "click":
            duration = 0.03
            t = np.linspace(0, duration, int(sample_rate * duration))
            # High frequency click with sharp decay
            samples = np.sin(2 * np.pi * 3000 * t) * np.exp(-t * 200)
        elif name == "shot": # Generic shot sound
            duration = 0.15
            samples = np.random.uniform(-1, 1, int(sample_rate * duration))
            t = np.linspace(0, duration, len(samples))
            punch = np.sin(2 * np.pi * 100 * t) * np.exp(-t * 30)
            samples = samples * np.exp(-t * 50) + punch * 0.6
        elif name in ["pistol", "uzi", "minigun"]:
            duration = 0.2
            samples = np.random.uniform(-1, 1, int(sample_rate * duration))
            t = np.linspace(0, duration, len(samples))
            # Noise mixed with low punch
            pulse = np.sin(2 * np.pi * 60 * t) * np.exp(-t * 20)
            samples = samples * np.exp(-t * 40) + pulse * 0.5
        elif name == "shotgun":
            duration = 0.4
            samples = np.random.uniform(-1, 1, int(sample_rate * duration))
            t = np.linspace(0, duration, len(samples))
            pulse = np.sin(2 * np.pi * 50 * t) * np.exp(-t * 10)
            samples = samples * np.exp(-t * 15) + pulse * 0.7
        elif name == "sniper":
            duration = 0.6
            samples = np.random.uniform(-1, 1, int(sample_rate * duration))
            t = np.linspace(0, duration, len(samples))
            pulse = np.sin(2 * np.pi * 40 * t) * np.exp(-t * 5)
            samples = samples * np.exp(-t * 10) + pulse * 0.8
        elif name == "rocket":
            duration = 0.6
            t = np.linspace(0, duration, int(sample_rate * duration))
            samples = np.random.uniform(-1, 1, len(t)) * (1 - t/duration)
            samples += np.sin(2 * np.pi * 80 * t) * 0.6
        elif name == "explosion":
            duration = 1.2
            samples = np.random.uniform(-1, 1, int(sample_rate * duration))
            t = np.linspace(0, duration, len(samples))
            # Heavy low-end explosion
            low_end = np.sin(2 * np.pi * 40 * t) * np.exp(-t * 3)
            samples = samples * np.exp(-t * 4) + low_end
        elif name == "enemy_hit":
            duration = 0.15
            t = np.linspace(0, duration, int(sample_rate * duration))
            samples = np.sin(2 * np.pi * 120 * t) * np.exp(-t * 30)
            samples += np.random.uniform(-0.5, 0.5, len(t)) * np.exp(-t * 60)
        elif name == "enemy_death":
            duration = 0.8
            samples = np.random.uniform(-1, 1, int(sample_rate * duration))
            t = np.linspace(0, duration, len(samples))
            # Boom on death
            low_boom = np.sin(2 * np.pi * 50 * t) * np.exp(-t * 4)
            samples = samples * np.exp(-t * 6) + low_boom
        elif name == "player_hit":
            duration = 0.25
            samples = np.random.uniform(-0.6, 0.6, int(sample_rate * duration))
            t = np.linspace(0, duration, len(samples))
            samples *= np.exp(-t * 15)
        elif name == "chest_open":
            duration = 0.5
            t = np.linspace(0, duration, int(sample_rate * duration))
            samples = np.random.uniform(-0.4, 0.4, len(t)) * np.exp(-t * 5) + np.sin(2 * np.pi * 220 * t) * 0.3 * np.exp(-t * 10)
        elif name == "pickup":
            duration = 0.1
            t = np.linspace(0, duration, int(sample_rate * duration))
            samples = np.sin(2 * np.pi * 1200 * t) * np.exp(-t * 40)
        elif name == "heal":
            duration = 0.15
            t = np.linspace(0, duration, int(sample_rate * duration))
            # Faster pitch sweep, shorter and cleaner
            sweep_freq = 600 + 400 * t/duration
            samples = np.sin(2 * np.pi * sweep_freq * t) * (1 - t/duration)

        # Convert to 16-bit PCM and normalize
        max_vol = np.max(np.abs(samples))
        if max_vol > 0: samples = samples / max_vol
        samples = (samples * 32767).astype(np.int16)
        
        stereo_samples = np.zeros((len(samples), 2), dtype=np.int16)
        stereo_samples[:, 0] = samples
        stereo_samples[:, 1] = samples
        return pygame.sndarray.make_sound(stereo_samples)

    def _play_sfx(self, name, volume=1.0, room_coords=None):
        # Room Filtering: only hear sounds in the room you are currently in
        if room_coords is not None:
             local_player = self.players.get(self.local_id)
             if local_player and local_player.current_room_coords != room_coords:
                 return

        if name in self.sounds:
            sound = self.sounds[name]
            sound.set_volume(volume * self.game_volume)
            # Use an available channel to avoid cutting off when replayed rapidly
            try:
                ch = pygame.mixer.find_channel(True)
                if ch:
                    ch.set_volume(volume * self.game_volume)
                    ch.play(sound)
                else:
                    sound.play()
            except Exception:
                # Fallback
                sound.play()

    def _play_music(self, path):
        if self.current_music == path:
            return
        try:
            full_path = resource_path(path)
            if os.path.exists(full_path):
                pygame.mixer.music.load(full_path)
                pygame.mixer.music.set_volume(self.music_volume)
                pygame.mixer.music.play(-1)
                self.current_music = path
            else:
                print(f"Warning: Music {path} not found.")
        except Exception as e:
            print(f"Music play error: {e}")

    def _update_audio_volumes(self):
        pygame.mixer.music.set_volume(self.music_volume)
        for sound in self.sounds.values():
            # Note: Individual sound volumes are set at play time, but we could update them here if needed
            pass

    def _play_weapon_sfx(self, weapon_name, room_coords=None):
        # Play per-weapon sound if available, else fallback to generic shot
        sound = None
        try:
            sound = self.weapon_sounds.get(weapon_name)
        except Exception:
            sound = None

        if sound:
            # Play on available channel to avoid cutting off
            try:
                ch = pygame.mixer.find_channel(True)
                if ch:
                    ch.set_volume(self.game_volume)
                    ch.play(sound)
                else:
                    sound.play()
            except Exception:
                sound.play()
        else:
            self._play_sfx("shot", room_coords=room_coords)

    def _stop_all_weapon_sounds(self):
        """Stops all looping weapon sounds and clears the tracker."""
        if hasattr(self, 'weapon_channels'):
            for pid, ch in list(self.weapon_channels.items()):
                try:
                    ch.stop()
                except Exception:
                    pass
            self.weapon_channels.clear()

    def _sanitize_ip_text(self, text):
        if not text:
            return ""
        try:
            text = str(text)
        except Exception:
            return ""
        text = text.replace("\x00", "")
        text = "".join(ch for ch in text if (ch.isdigit() or ch == "."))
        return text[:15]

    def _leave_lobby_to_menu(self):
        # Notify others that we're leaving
        try:
            self.network.send({"type": "PLAYER_LEFT", "id": self.local_id})
        except Exception:
            pass
        try:
            self.network.shutdown()
        except Exception:
            pass
        self.network = NetworkManager()
        self._stop_all_weapon_sounds()
        self.state = "MENU"
        self.menu_screen = "MAIN"
        self.name_input_active = False
        self.menu_click_held = False
        self.players = {}
        self.spectating_id = None
        self.game_over = False
        self.seed = None
        self.dungeon = None
        self.join_ip = ""
        self.local_id = str(random.randint(1000, 9999))

    def _broadcast_player_info(self):
        self.network.send({
            "type": "PLAYER_INFO",
            "id": self.local_id,
            "name": self.local_name,
            "color": self.local_name_color
        })
    
    def _pick_random_floor_color(self):
        dark_colors = [
            (20, 20, 20),   # Dark Grey
            (30, 10, 10),   # Dark Red
            (10, 30, 10),   # Dark Green
            (10, 10, 30),   # Dark Blue
            (30, 30, 10),   # Dark Yellow/Olive
            (30, 10, 30),   # Dark Purple
            (10, 30, 30),   # Dark Cyan
            (15, 15, 25),   # Midnight Blue
            (25, 15, 15),   # Deep Maroon
            (15, 25, 15),   # Forest Shadow
            (20, 10, 20),   # Deep Plum
            (10, 20, 20),   # Dark Teal
            (25, 20, 10),   # Muted Bronze
            (15, 15, 15),   # Near Black
            (20, 25, 30),   # Cold Slate
        ]
        return random.choice(dark_colors)

    def run(self):
        while self.running:
            dt = self.clock.tick(FPS)
            self.handle_events()
            self.update(dt)
            self.draw()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            if event.type == pygame.VIDEORESIZE and not self.fullscreen:
                self.screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)

            if self.state == "SPLASH":
                if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    self.state = "MENU"
                    self.menu_screen = "MAIN"
                    continue

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.menu_click_held = False
                self.dragging_game = False
                self.dragging_music = False
            
            if self.state == "GAME":
                 if event.type == pygame.KEYDOWN:
                     if event.key == pygame.K_ESCAPE:
                         self.pause_menu_open = not self.pause_menu_open
                     if event.key == pygame.K_j:
                         # Accept level transition
                         if self.level_transition_pending and self.local_id not in self.level_transition_accepted:
                             self.level_transition_accepted.add(self.local_id)
                             self.network.send({"type": "LEVEL_ACCEPT", "id": self.local_id})
                             
                             # If host, check if all accepted
                             if self.network.is_host:
                                 if len(self.level_transition_accepted) >= len(self.players):
                                     self.floor_number += 1
                                     new_seed = random.randint(10000, 99999)
                                     new_color = self._pick_random_floor_color()
                                     self.network.send({"type": "LEVEL_START", "seed": new_seed, "floor_color": new_color})
                                     self._start_new_floor(new_seed, new_color)

            # Input Handling
            if self.state == "MENU":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    layout = self._get_menu_layout()
                    mouse_pos = event.pos

                    # Username input focus
                    if self.menu_screen in ["MAIN", "MULTIPLAYER"]:
                        self.name_input_active = self._get_name_input_rect().collidepoint(mouse_pos)

                    # Button clicks (edge-trigger)
                    if not self.menu_click_held:
                        self.menu_click_held = True

                        if self.menu_screen == "MAIN":
                            if layout["main"]["Singleplayer"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self._start_singleplayer()
                            elif layout["main"]["Multiplayer"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.menu_screen = "MULTIPLAYER"
                                self.name_input_active = False
                            elif layout["main"]["Custom"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.menu_screen = "CUSTOM"
                                self.custom_floor = 1
                                self.custom_weapon_idx = 0
                                self.available_weapons = ["Pistol", "Uzi", "Shotgun", "SniperRifle", "Minigun", "RocketLauncher", "LaserRifle", "GrenadeLauncher", "DualPistols"]
                                self.name_input_active = False
                            elif layout["main"]["Settings"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.menu_screen = "SETTINGS"
                                self.name_input_active = False
                            elif layout["main"]["Quit"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.running = False

                        elif self.menu_screen == "MULTIPLAYER":
                            if layout["multiplayer"]["Back"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.menu_screen = "MAIN"
                            elif layout["multiplayer"]["Host"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                if self.network.host_game():
                                    self.state = "LOBBY"
                                    self.local_id = "HOST"
                                    self._broadcast_player_info()
                            elif layout["multiplayer"]["Join"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.menu_screen = "JOIN_IP"
                                if not hasattr(self, 'join_ip'):
                                    self.join_ip = ""
                                self.name_input_active = False

                        elif self.menu_screen == "JOIN_IP":
                            if layout["join_ip"]["Back"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.menu_screen = "MULTIPLAYER"
                            elif layout["join_ip"]["Connect"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                target_ip = self.join_ip if self.join_ip else "127.0.0.1"
                                if self.network.join_game(target_ip):
                                    self.state = "LOBBY"
                                    self.state = "LOBBY"
                                    self.local_id = str(random.randint(1000,9999))
                                    self._broadcast_player_info()

                        elif self.menu_screen == "CUSTOM":
                            if layout["custom"]["Back"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.menu_screen = "MAIN"
                            elif layout["custom"]["Start"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.floor_number = self.custom_floor
                                self.start_weapon = self.available_weapons[self.custom_weapon_idx]
                                self._start_singleplayer(custom=True)
                            elif layout["custom"]["FloorDown"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.custom_floor = max(1, self.custom_floor - 1)
                            elif layout["custom"]["FloorUp"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.custom_floor = min(100, self.custom_floor + 1)
                            elif layout["custom"]["WeaponDown"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.custom_weapon_idx = (self.custom_weapon_idx - 1) % len(self.available_weapons)
                            elif layout["custom"]["WeaponUp"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.custom_weapon_idx = (self.custom_weapon_idx + 1) % len(self.available_weapons)

                        elif self.menu_screen == "SETTINGS":
                            if layout["settings"]["Back"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self.menu_screen = "MAIN"
                            elif layout["settings"]["Fullscreen"].collidepoint(mouse_pos):
                                self._play_sfx("click")
                                self._apply_fullscreen(not self.fullscreen)
                            elif layout["settings"]["GameVolume"].collidepoint(mouse_pos):
                                self.dragging_game = True
                            elif layout["settings"]["MusicVolume"].collidepoint(mouse_pos):
                                self.dragging_music = True

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if self.menu_screen != "MAIN":
                            self.menu_screen = "MAIN"
                            self.name_input_active = False

                    if self.menu_screen == "JOIN_IP":
                        if event.key == pygame.K_BACKSPACE:
                            self.join_ip = self.join_ip[:-1]
                        elif event.key == pygame.K_RETURN:
                            target_ip = self.join_ip if self.join_ip else "127.0.0.1"
                            if self.network.join_game(target_ip):
                                self.state = "LOBBY"
                                self.local_id = str(random.randint(1000,9999))
                                self._broadcast_player_info()
                        elif event.key == pygame.K_v and (pygame.key.get_mods() & pygame.KMOD_CTRL):
                            try:
                                if hasattr(pygame.scrap, "get_text"):
                                    clip_text = pygame.scrap.get_text()
                                else:
                                    pygame.scrap.init()
                                    clip = pygame.scrap.get(pygame.SCRAP_TEXT)
                                    clip_text = clip.decode('utf-8', errors='ignore') if clip else ""
                                clip_text = self._sanitize_ip_text(clip_text.strip())
                                self.join_ip = self._sanitize_ip_text(self.join_ip + clip_text)
                            except Exception:
                                pass
                        else:
                            if len(self.join_ip) < 15 and (event.unicode.isdigit() or event.unicode == "."):
                                self.join_ip = self._sanitize_ip_text(self.join_ip + event.unicode)
                    else:
                        if event.key == pygame.K_BACKSPACE:
                            if self.name_input_active:
                                self.local_name = self.local_name[:-1]
                                self._save_settings()
                        elif event.key == pygame.K_TAB:
                            if self.name_input_active:
                                try:
                                    idx = self.name_colors.index(self.local_name_color)
                                    self.local_name_color = self.name_colors[(idx + 1) % len(self.name_colors)]
                                except ValueError:
                                    self.local_name_color = self.name_colors[0]
                        elif self.name_input_active and len(event.unicode) > 0 and event.unicode.isprintable():
                            if len(self.local_name) < 12:
                                self.local_name += event.unicode
                                self._save_settings()
            
            elif self.state == "LOBBY":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    sw, sh = self.screen.get_size()
                    back_rect = pygame.Rect(sw - 220, 40, 200, 60)
                    start_rect = pygame.Rect(sw - 220, sh - 80, 200, 60)
                    if not self.menu_click_held:
                        self.menu_click_held = True
                        if back_rect.collidepoint(event.pos):
                            self._play_sfx("click")
                            self._leave_lobby_to_menu()
                            continue
                        if self.network.is_host and start_rect.collidepoint(event.pos):
                            self._play_sfx("click")
                            self.seed = random.randint(0, 100000)
                            self.floor_color = self._pick_random_floor_color()
                            self.network.send({"type": "START_GAME", "seed": self.seed, "floor_color": self.floor_color})
                            self._start_game()
                            continue
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE and self.network.is_host:
                        # Generate Seed
                        # Generate Seed
                        self.seed = random.randint(0, 100000)
                        self.floor_color = self._pick_random_floor_color()
                        # Tell everyone to start
                        self.network.send({"type": "START_GAME", "seed": self.seed, "floor_color": self.floor_color})
                        self._start_game()

                    
                    elif event.key == pygame.K_j:
                        # Accept level transition
                        if self.level_transition_pending and self.local_id not in self.level_transition_accepted:
                            self.level_transition_accepted.add(self.local_id)
                            self.network.send({"type": "LEVEL_ACCEPT", "id": self.local_id})
                            
                            # If host, check if all accepted
                            if self.network.is_host:
                                if len(self.level_transition_accepted) >= len(self.players):
                                    # All accepted, start new level
                                    self.floor_number += 1
                                    new_seed = random.randint(10000, 99999)
                                    new_color = self._pick_random_floor_color()
                                    self.network.send({"type": "LEVEL_START", "seed": new_seed, "floor_color": new_color})
                                    self._start_new_floor(new_seed, new_color)

    def _start_game(self):
        print(f"Starting game with seed {self.seed}")
        # self.floor_color is already set by host or network event
        self.dungeon_gen = DungeonGenerator(self.seed)
        self.dungeon, self.chests = self.dungeon_gen.generate()
        self.state = "GAME"
        self.dropped_weapons = []

        # Spawn local player in (0,0) center
        start_room = self.dungeon[(0,0)]
        center = start_room.get_world_rect().center
        self.players[self.local_id] = Player(self.local_id, center[0], center[1], True)
        
        if self.network.is_host:
             # self.spawn_enemy(center[0] + 200, center[1] + 200, "charger") # REMOVED DEBUG
             pass
        
        # Init local player name info
        if self.local_id in self.players:
            self.players[self.local_id].name = self.local_name
            self.players[self.local_id].name_color = self.local_name_color
            # Broadcast again to be sure
            self._broadcast_player_info()
            
            # Host marks start room as discovered
            if self.network.is_host:
                self.network.send({"type": "ROOM_DISCOVERED", "coords": (0,0)})
                self.visited_rooms.add((0,0)) # Host local add

    def _start_singleplayer(self, custom=False):
        self.network.is_host = True
        self.network.connected = False
        self.local_id = "HOST"
        self._broadcast_player_info()
        self.seed = random.randint(0, 100000)
        self.floor_color = self._pick_random_floor_color()
        self._start_game(custom)

    def _start_game(self, custom=False):
        print(f"Starting game with seed {self.seed}")
        # self.floor_color is already set by host or network event
        self.dungeon_gen = DungeonGenerator(self.seed)
        self.dungeon, self.chests = self.dungeon_gen.generate()
        self.state = "GAME"
        self.dropped_weapons = []

        # Spawn local player in (0,0) center
        start_room = self.dungeon[(0,0)]
        center = start_room.get_world_rect().center
        self.players[self.local_id] = Player(self.local_id, center[0], center[1], True)
        
        # Apply local name and color
        self.players[self.local_id].name = self.local_name
        self.players[self.local_id].name_color = self.local_name_color
        self._broadcast_player_info()
        
        if custom:
            # Equip custom weapon
            wep_name = getattr(self, 'start_weapon', 'Pistol')
            # Map string to class instance
            weapon_map = {
                "Pistol": Pistol, "Uzi": Uzi, "Shotgun": Shotgun, "SniperRifle": SniperRifle,
                "Minigun": Minigun, "RocketLauncher": RocketLauncher, "LaserRifle": LaserRifle,
                "GrenadeLauncher": GrenadeLauncher, "DualPistols": DualPistols
            }
            if wep_name in weapon_map:
                self.players[self.local_id].weapon = weapon_map[wep_name]()

    def _apply_fullscreen(self, enabled):
        self.fullscreen = bool(enabled)
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.RESIZABLE)

    def _get_menu_layout(self):
        sw, sh = self.screen.get_size()
        button_w = min(360, sw - 420)
        button_h = 56
        gap = 16
        top_y = int(sh * 0.62)
        x = sw // 2 - button_w // 2

        main_labels = ["Singleplayer", "Multiplayer", "Custom", "Settings", "Quit"]
        main_rects = {}
        for i, label in enumerate(main_labels):
            main_rects[label] = pygame.Rect(x, top_y + i * (button_h + gap), button_w, button_h)

        mp_labels = ["Host", "Join", "Back"]
        mp_rects = {}
        for i, label in enumerate(mp_labels):
            mp_rects[label] = pygame.Rect(x, top_y + i * (button_h + gap), button_w, button_h)

        settings_rects = {
            "Fullscreen": pygame.Rect(x, top_y, button_w, button_h),
            "GameVolume": pygame.Rect(x, top_y + (button_h + 35), button_w, button_h - 10),
            "MusicVolume": pygame.Rect(x, top_y + 2 * (button_h + 35), button_w, button_h - 10),
            "Back": pygame.Rect(x, top_y + 3 * (button_h + 35), button_w, button_h),
        }

        join_ip_rects = {
            "Connect": pygame.Rect(x, top_y, button_w, button_h),
            "Back": pygame.Rect(x, top_y + (button_h + gap), button_w, button_h),
            "InputBox": pygame.Rect(sw // 2 - 200, top_y - 80, 400, 60)
        }

        custom_rects = {
            "FloorDown": pygame.Rect(sw // 2 - 150, top_y, 40, 40),
            "FloorUp": pygame.Rect(sw // 2 + 110, top_y, 40, 40),
            "WeaponDown": pygame.Rect(sw // 2 - 150, top_y + 60, 40, 40),
            "WeaponUp": pygame.Rect(sw // 2 + 110, top_y + 60, 40, 40),
            "Start": pygame.Rect(x, top_y + 140, button_w, button_h),
            "Back": pygame.Rect(x, top_y + 200, button_w, button_h)
        }

        return {
            "sw": sw,
            "sh": sh,
            "main": main_rects,
            "multiplayer": mp_rects,
            "settings": settings_rects,
            "join_ip": join_ip_rects,
            "custom": custom_rects,
        }

    def _get_pause_menu_layout(self):
        sw, sh = self.screen.get_size()
        w, h = 300, 50
        x = sw // 2 - w // 2
        y_start = sh // 2 - 120
        gap = 80
        
        return {
            "Fullscreen": pygame.Rect(x, y_start, w, h),
            "GameVolume": pygame.Rect(x, y_start + gap + 25, w, 20),
            "MusicVolume": pygame.Rect(x, y_start + 2*gap + 25, w, 20),
            "Quit": pygame.Rect(x, y_start + 3*gap, w, h)
        }

    def _draw_menu_button(self, rect, text, hovered):
        base = (40, 40, 60)
        hover = (70, 70, 90)
        pygame.draw.rect(self.screen, hover if hovered else base, rect, border_radius=10)
        pygame.draw.rect(self.screen, WHITE, rect, 2, border_radius=10)
        self.draw_text(text, rect.center, WHITE, size=32)

    def _draw_volume_slider(self, rect, label, value):
        # Draw Label (Shifted further up to avoid overlap)
        self.draw_text(f"{label}: {int(value * 100)}%", (rect.centerx, rect.top - 20), WHITE, size=22)
        
        # Draw Slot Background
        slot_height = 8
        slot_rect = pygame.Rect(rect.left, rect.centery - slot_height // 2, rect.width, slot_height)
        pygame.draw.rect(self.screen, (30, 30, 50), slot_rect, border_radius=slot_height // 2)
        
        # Draw Progress Fill
        fill_width = int(rect.width * value)
        if fill_width > 0:
            fill_rect = pygame.Rect(rect.left, rect.centery - slot_height // 2, fill_width, slot_height)
            # Emerald gradient-like color
            pygame.draw.rect(self.screen, (80, 255, 120), fill_rect, border_radius=slot_height // 2)
        
        # Draw Handle with glow effect
        handle_x = rect.left + int(rect.width * value)
        handle_radius = 12
        
        # Subtle glow
        glow_surf = pygame.Surface((handle_radius * 4, handle_radius * 4), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (80, 255, 120, 40), (handle_radius * 2, handle_radius * 2), handle_radius * 2)
        self.screen.blit(glow_surf, (handle_x - handle_radius * 2, rect.centery - handle_radius * 2))
        
        # Main handle
        pygame.draw.circle(self.screen, WHITE, (handle_x, rect.centery), handle_radius)
        pygame.draw.circle(self.screen, (60, 60, 80), (handle_x, rect.centery), handle_radius - 3, 2)

    def _draw_menu_starfield(self):
        sw, sh = self.screen.get_size()
        cx, cy = sw / 2, sh / 2

        if not hasattr(self, 'bg_vignette') or self.bg_vignette.get_size() != (sw, sh):
            self.bg_vignette = pygame.Surface((sw, sh))
            self.bg_vignette.fill((5, 5, 10))

        self.screen.blit(self.bg_vignette, (0, 0))

        for star in self.menu_stars:
            star["z"] -= self.star_speed
            if star["z"] <= 0:
                star["z"] = self.star_depth
                star["x"] = random.randint(-2000, 2000)
                star["y"] = random.randint(-2000, 2000)

            fov = 400
            safe_z = max(1, star["z"])
            sx = cx + (star["x"] / safe_z) * fov
            sy = cy + (star["y"] / safe_z) * fov

            tail_z = safe_z + 25
            tx = cx + (star["x"] / tail_z) * fov
            ty = cy + (star["y"] / tail_z) * fov

            if 0 <= sx <= sw and 0 <= sy <= sh:
                if abs(sx - cx) < sw * 0.18 and abs(sy - cy) < sh * 0.16:
                    continue
                brightness = 1.0 - (safe_z / self.star_depth)
                brightness = max(0, min(1, brightness * 1.5))
                color = (
                    int(star["color"][0] * brightness),
                    int(star["color"][1] * brightness),
                    int(star["color"][2] * brightness)
                )
                thickness = star["base_size"] * (1.0 + (1.0 - safe_z / self.star_depth) * 2)
                pygame.draw.line(self.screen, color, (tx, ty), (sx, sy), max(1, int(thickness)))

    def _quit_to_menu(self):
        # Notify others that we're leaving
        try:
            self.network.send({"type": "PLAYER_LEFT", "id": self.local_id})
        except Exception:
            pass
        try:
            self.network.shutdown()
        except Exception:
            pass
        self.network = NetworkManager()
        self._stop_all_weapon_sounds()

        self.pause_menu_open = False
        self.pause_click_held = False
        self.shoot_pressed = False
        self.spectating_id = None

        self.players = {}
        self.dungeon = None
        self.current_room_coords = (0, 0)
        self.camera = pygame.math.Vector2(0, 0)
        self.bullets = []
        self.dropped_weapons = []
        self.heal_pickups = []
        self.beams = []
        self.enemies = {}
        self.enemy_counter = 0
        self.bosses = {}
        self.boss_counter = 0
        self.chests = []
        self.visited_rooms = set()
        self.game_over = False
        self.floor_number = 1
        self.trapdoor = None
        self.trapdoor_room = None
        self.level_transition_pending = False
        self.level_transition_requester = None
        self.level_transition_accepted = set()
        self.boss_kills_total = 0  # Reset boss kills for difficulty scaling

        self.state = "MENU"
        self.menu_screen = "MAIN"

    def spawn_enemy(self, x, y, type, room_coords=None, lifespan=None):
        eid = str(self.enemy_counter)
        self.enemy_counter += 1
        self.enemies[eid] = Enemy(eid, x, y, type, room_coords, lifespan)
        
        # Difficulty scaling: regular enemy HP increases only start after floor 8
        floor_num = getattr(self, 'floor_number', 1)
        if floor_num >= 9:
            # apply HP bonuses relative to floors after 8
            hp_bonus = (floor_num - 8) // 3
        else:
            hp_bonus = 0
        self.enemies[eid].hp += hp_bonus
        
        self.network.send({"type": "ENEMY_SPAWN", "id": eid, "x": x, "y": y, "etype": type, "room": room_coords})
        return eid

    def spawn_boss(self, x, y, room_coords=None):
        bid = f"boss_{self.boss_counter}"
        self.boss_counter += 1
        
        # Prevent same boss twice in a row
        available_variants = [v for v in Boss.VARIANTS if v != self.last_boss_variant]
        variant = random.choice(available_variants)
        self.last_boss_variant = variant
        
        self.bosses[bid] = Boss(bid, x, y, room_coords, variant=variant)
        
        # Difficulty scaling: every 3rd boss killed increases boss HP by 100
        boss_kills = getattr(self, 'boss_kills_total', 0)
        hp_bonus = (boss_kills // 3) * 100
        self.bosses[bid].hp += hp_bonus
        self.bosses[bid].max_hp += hp_bonus
        
        self.network.send({"type": "BOSS_SPAWN", "id": bid, "x": x, "y": y, "room": room_coords, "variant": variant})

    def _start_new_floor(self, new_seed, new_color, reset_players=False):
        """Reset game state for new floor/level."""
        self.seed = new_seed
        self._stop_all_weapon_sounds()
        self.floor_color = new_color
        self.dungeon_gen = DungeonGenerator(self.seed)
        self.dungeon, self.chests = self.dungeon_gen.generate()
        
        # Reset entities
        self.enemies = {}
        self.enemy_counter = 0
        self.bosses = {}
        self.boss_counter = 0
        self.bullets = []
        self.beams = []
        self.dropped_weapons = [] # New list for ground items
        self.trapdoor = None
        self.trapdoor_room = None
        self.visited_rooms = set()
        self.level_transition_pending = False
        self.level_transition_requester = None
        self.level_transition_accepted = set()
        
        # Reset player position
        start_room = self.dungeon[(0,0)]
        center = start_room.get_world_rect().center
        for player in self.players.values():
            player.rect.center = center
            player.current_room_coords = (0, 0)
            if reset_players:
                player.hp = player.max_hp
                player.weapon = Pistol()
                player.alive = True
            else:
                if player.hp <= 0:
                    player.hp = player.max_hp
                player.alive = True
        
        self.spectating_id = None
        self.game_over = False # Reset game over flag
        print(f"Started Floor {self.floor_number} with seed {self.seed}")

    def update(self, dt):
        # Handle Music Transitions
        if self.state in ["SPLASH", "MENU", "LOBBY"]:
            self._play_music("menumusic.mp3")
        elif self.state == "GAME":
            self._play_music("gamemusic.mp3")

        if self.state == "SPLASH":
            if self.splash_image and self.splash_rect:
                sw, sh = self.screen.get_size()
                self.splash_rect.center = (sw // 2, sh // 2)
            elapsed = pygame.time.get_ticks() - self.splash_start_time
            if elapsed >= self.splash_duration:
                self.state = "MENU"
            return

        # Handle Volume Dragging
        if self.menu_screen == "SETTINGS" or (self.state == "GAME" and self.pause_menu_open):
            mouse_pos = pygame.mouse.get_pos()
            if self.menu_screen == "SETTINGS":
                layout = self._get_menu_layout()["settings"]
            else:
                layout = self._get_pause_menu_layout()
                
            if self.dragging_game:
                rect = layout["GameVolume"]
                val = (mouse_pos[0] - rect.left) / rect.width
                self.game_volume = max(0.0, min(1.0, val))
                self._update_audio_volumes()
                self._save_settings()
            elif self.dragging_music:
                rect = layout["MusicVolume"]
                val = (mouse_pos[0] - rect.left) / rect.width
                self.music_volume = max(0.0, min(1.0, val))
                self._update_audio_volumes()
                self._save_settings()

        # Process Network Events
        events = self.network.get_events()
        for event_tuple in events:
            # Unpack tuple (data, conn)
            # If it's a legacy structure (unlikely with our change), handle it safe
            if isinstance(event_tuple, tuple) and len(event_tuple) == 2:
                data, conn = event_tuple
            else:
                data, conn = event_tuple, None

            if data.get("type") == "START_GAME":
                self.seed = data["seed"]
                self.floor_color = data.get("floor_color", (20, 20, 20))
                self._start_game()
            elif data.get("type") == "PLAYER_UPDATE":
                pid = data["id"]
                pos = data["pos"]
                angle = data.get("angle", 0)
                if pid != self.local_id:
                     if pid not in self.players:
                         self.players[pid] = Player(pid, pos[0], pos[1])
                         # Request info? Or wait for broadcast. 
                         # usually broadcast happens enough.
                     self.players[pid].rect.center = pos
                     self.players[pid].set_angle(angle)
                     # Update room coords for minimap
                     self.players[pid].current_room_coords = (int(pos[0] // ROOM_SIZE), int(pos[1] // ROOM_SIZE))
                
                # Host: Relay PLAYER_UPDATE to all clients so they can see each other
                if self.network.is_host:
                    self.network.send(data)
            elif data.get("type") == "PLAYER_INFO":
                pid = data["id"]
                if pid in self.players:
                    self.players[pid].name = data["name"]
                    self.players[pid].name_color = data["color"]
                else:
                    self.players[pid] = Player(pid, 0, 0)
                    self.players[pid].name = data["name"]
                    self.players[pid].name_color = data["color"]
                
                # Map connection to ID for host disconnect handling
                if self.network.is_host and conn:
                    self.client_conns[conn] = pid

                
                # Host Logic: Relay and Sync
                if self.network.is_host:
                    # 1. Relay this new/updated player to everyone else
                    self.network.send(data)
                    
                    # 2. Broadcast ALL other known players (including Host) to everyone (simplest way to ensure sync)
                    # Host info
                    self.network.send({
                        "type": "PLAYER_INFO",
                        "id": self.local_id,
                        "name": self.local_name,
                        "color": self.local_name_color
                    })
                    # Other players info
                    for other_pid, other_p in self.players.items():
                        if other_pid == pid: continue
                        if other_pid == self.local_id: continue
                        if hasattr(other_p, 'name'):
                            self.network.send({
                                "type": "PLAYER_INFO",
                                "id": other_pid,
                                "name": other_p.name,
                                "color": other_p.name_color
                            })
                
            elif data.get("type") == "BULLET_EXPLODE":
                bid = data["id"]
                for b in self.bullets:
                    if b.owner_id == bid or (hasattr(b, 'bullet_id') and b.bullet_id == bid):
                        b.explode()
                        break
                    
                    # 3. Sync World State (Visited Rooms) to ensure no "leaks" of missing info
                    for room_coords in self.visited_rooms:
                        self.network.send({"type": "ROOM_DISCOVERED", "coords": room_coords})
                    
                    # 4. Sync Trapdoor if exists
                    if self.trapdoor:
                        self.network.send({"type": "TRAPDOOR_SPAWN", "x": self.trapdoor.x, "y": self.trapdoor.y, "room": self.trapdoor_room})

            elif data.get("type") == "SHOOT":
                # Spawn bullet from other player
                pid = data["id"]
                if pid != self.local_id:
                    speed = data.get("speed", 15)
                    btype = data.get("btype", "normal")
                    dmg = data.get("damage", 10)
                    color = data.get("color", RED)
                    wep = data.get("wep", "Pistol")
                    spawn_room = (int(data["x"] // ROOM_SIZE), int(data["y"] // ROOM_SIZE))
                    
                    self._play_weapon_sfx(wep, room_coords=spawn_room)
                    self.bullets.append(Bullet(data["x"], data["y"], data["angle"], pid, speed, color, btype, dmg, spawn_room))
                
                # Host Relay
                if self.network.is_host:
                    self.network.send(data)
            elif data.get("type") == "CHEST_OPENED":
                idx = data["index"]
                if 0 <= idx < len(self.chests):
                    self.chests[idx].opened = True
                
                # Host Relay
                if self.network.is_host:
                    self.network.send(data)
            elif data.get("type") == "ENEMY_SPAWN":
                if not self.network.is_host:
                     r_coords = tuple(data["room"]) if data["room"] else None
                     enemy = Enemy(data["id"], data["x"], data["y"], data["etype"], r_coords)
                     self.enemies[data["id"]] = enemy
                     if r_coords and r_coords in self.dungeon:
                         self.dungeon[r_coords].enemies.append(enemy)
            elif data.get("type") == "ENEMY_UPDATE":
                 if not self.network.is_host:
                     eid = data["id"]
                     if eid in self.enemies:
                         self.enemies[eid].rect.center = data["pos"]
                         # Sync sniper laser target
                         if "laser_target" in data:
                             self.enemies[eid].laser_target = data["laser_target"]
                         elif hasattr(self.enemies[eid], 'laser_target'):
                             self.enemies[eid].laser_target = None
                         
                         if "shield_angle" in data:
                             self.enemies[eid].shield_angle = data["shield_angle"]
                         
                         if "is_phased" in data:
                             self.enemies[eid].is_phased = data["is_phased"]
                     else:
                         # Late join or missed spawn?
                         self.enemies[eid] = Enemy(eid, data["pos"][0], data["pos"][1], data["etype"])
            elif data.get("type") == "BEAM":
                    self.beams.append(EnergyBeam((data["x"], data["y"]), data["angle"]))
            elif data.get("type") == "ENEMY_DEATH":
                eid = data["id"]
                if eid in self.enemies:
                    # Spawn particles before removing
                    enemy = self.enemies[eid]
                    create_particles(enemy.rect.center, 20, enemy.color, 2, 8, 20, 50)
                    self._play_sfx("enemy_death", room_coords=enemy.room_coords)
                    del self.enemies[eid]
            elif data.get("type") == "BOSS_DEATH":
                bid = data["id"]
                if bid in self.bosses:
                    boss = self.bosses[bid]
                    create_particles(boss.rect.center, 100, boss.color, 3, 10, 40, 80)
                    self._play_sfx("explosion", room_coords=boss.room_coords)
                    del self.bosses[bid]
            elif data.get("type") == "ENEMY_TELEPORT":
                eid = data["id"]
                if eid in self.enemies:
                    enemy = self.enemies[eid]
                    create_particles(enemy.rect.center, 20, enemy.color, 2, 5, 10, 30)
                    enemy.pos = pygame.math.Vector2(data["x"], data["y"])
                    enemy.rect.center = enemy.pos
                    create_particles(enemy.rect.center, 20, enemy.color, 2, 5, 10, 30)
            elif data.get("type") == "ROOM_CLEARED":
                 pos = data["coords"]
                 if tuple(pos) in self.dungeon:
                     self.dungeon[tuple(pos)].cleared = True
            elif data.get("type") == "TRAPDOOR_SPAWN":
                 self.trapdoor = pygame.Rect(data["x"], data["y"], 80, 80)
                 self.trapdoor_room = tuple(data["room"])

            elif data.get("type") == "ROOM_ENTER":
                 # Client notified host they entered a room - host spawns enemies
                 if self.network.is_host:
                     r_coords = tuple(data["room"])
                     
                     # Broadcast discovery to all
                     self.network.send({"type": "ROOM_DISCOVERED", "coords": r_coords})
                     self.visited_rooms.add(r_coords) # Host adds locally
                     
                     # Update player's room coord on host side so activation_timer can tick
                     pid = data["id"]
                     if pid in self.players:
                         self.players[pid].current_room_coords = r_coords

                     if r_coords in self.dungeon:
                         curr_room = self.dungeon[r_coords]
                         if not curr_room.cleared and not hasattr(curr_room, 'has_spawned'):
                             curr_room.spawn_enemies_for_room(self)
                             curr_room.has_spawned = True
                             curr_room.activation_timer = 60
                             curr_room.enemies = [e for e in self.enemies.values() if e.room_coords == r_coords]
                             for e in curr_room.enemies:
                                 e.frozen = True
            
            elif data.get("type") == "ROOM_DISCOVERED":
                 # Everyone adds to visited
                 self.visited_rooms.add(tuple(data["coords"]))

            elif data.get("type") == "LEVEL_REQUEST":
                 # Another player wants to go to next level
                 self.level_transition_pending = True
                 self.level_transition_requester = data["id"]
                 # Reset acceptance if new request (though usually one time per floor)
                 # self.level_transition_accepted = set() 
                 # Add requester to accepted list immediately (they voted yes by requesting)
                 self.level_transition_accepted.add(data["id"])
            
            elif data.get("type") == "LEVEL_ACCEPT":
                 # A player accepted the level transition
                 self.level_transition_accepted.add(data["id"])
                 # Host checks if all players accepted
                 if self.network.is_host:
                     if len(self.level_transition_accepted) >= len(self.players):
                         self.floor_number += 1
                         new_seed = random.randint(10000, 99999)
                         new_color = self._pick_random_floor_color()
                         self.network.send({"type": "LEVEL_START", "seed": new_seed, "floor_color": new_color})
                         self._start_new_floor(new_seed, new_color)
            elif data.get("type") == "LEVEL_START":
                 # All players accepted, start new level
                 self.floor_number += 1
                 self._start_new_floor(data["seed"], data.get("floor_color", (20,20,20)))

            # --- ADD THESE EVENTS ---
            elif data.get("type") == "PLAYER_HIT":
                pid = data["id"]
                dmg = data["damage"]
                if pid in self.players:
                    p = self.players[pid]
                    p.hp -= dmg
                    # Visual feedback
                    create_particles(p.rect.center, 10, RED, 1, 4, 10, 20)
                    self._play_sfx("player_hit", room_coords=p.current_room_coords)
                
                # Host Relay
                if self.network.is_host:
                    self.network.send(data)

            elif data.get("type") == "PLAYER_DEATH":
                pid = data["id"]
                if pid in self.players:
                    self.players[pid].hp = 0
                    self.players[pid].alive = False
                    if pid == self.local_id:
                        self._stop_all_weapon_sounds()
                    create_particles(self.players[pid].rect.center, 50, PLAYER_COLOR, 2, 8, 30, 60)
                
                # Host Relay
                if self.network.is_host:
                    self.network.send(data)
            
            elif data.get("type") == "GAME_RESTART":
                # Reset game state for restart
                self.game_over = False
                self.floor_number = 1
                self._start_new_floor(data["seed"], data["floor_color"], reset_players=True)
            # ------------------------
            elif data.get("type") == "BOSS_SPAWN":
                 if not self.network.is_host:
                     self.bosses[data["id"]] = Boss(data["id"], data["x"], data["y"], tuple(data["room"]), data["variant"])
            elif data.get("type") == "BOSS_UPDATE":
                 if not self.network.is_host:
                     bid = data["id"]
                     if bid in self.bosses:
                         self.bosses[bid].rect.center = data["pos"]
                         self.bosses[bid].hp = data["hp"]
                         if "laser_target" in data:
                             self.bosses[bid].laser_target = data["laser_target"]
                         elif hasattr(self.bosses[bid], 'laser_target'):
                             self.bosses[bid].laser_target = None
            elif data.get("type") == "WEAPON_DROP":
                 # Remote drop visual
                 drop = DroppedWeapon(data["id"], data["class"], data["x"], data["y"])
                 self.dropped_weapons.append(drop)
                 
                 # Host Relay
                 if self.network.is_host:
                     self.network.send(data)

            elif data.get("type") == "WEAPON_PICKUP":
                 # Remote pickup removal
                 drop_id = data["id"]
                 self.dropped_weapons = [d for d in self.dropped_weapons if d.id != drop_id]
                 
                 # Host Relay
                 if self.network.is_host:
                     self.network.send(data)

            elif data.get("type") == "HEAL_DROP":
                 pickup = HealPickup(data["id"], data["x"], data["y"], data.get("amount", 1), tuple(data["room"]))
                 self.heal_pickups.append(pickup)
                 
                 # Host Relay
                 if self.network.is_host:
                     self.network.send(data)

            elif data.get("type") == "HEAL_PICKUP":
                 hid = data["id"]
                 self.heal_pickups = [h for h in self.heal_pickups if h.id != hid]
                 
                 # Host Relay
                 if self.network.is_host:
                     self.network.send(data)

            elif data.get("type") == "PLAYER_HEAL":
                 pid = data["id"]
                 amt = data.get("amount", 1)
                 if pid in self.players:
                     p = self.players[pid]
                     if getattr(p, "alive", True):
                         p.hp = min(p.max_hp, p.hp + amt)
                 
                 # Host Relay
                 if self.network.is_host:
                     self.network.send(data)

            elif data.get("type") == "PLAYER_KNOCKBACK":
                 pid = data["id"]
                 pos = data["pos"]
                 if pid in self.players:
                     self.players[pid].rect.center = pos
                     self.players[pid].current_room_coords = (int(pos[0] // ROOM_SIZE), int(pos[1] // ROOM_SIZE))
                 
                 # Host Relay
                 if self.network.is_host:
                     self.network.send(data)

            elif data.get("type") == "PLAYER_LEFT":
                # Player left the game/lobby - remove them
                pid = data["id"]
                if pid in self.players:
                    if pid == self.local_id:
                        self._stop_all_weapon_sounds()
                    del self.players[pid]
                # Host: Relay to all other clients
                if self.network.is_host:
                    self.network.send(data)

            elif data.get("type") == "DISCONNECT":
                # Internal disconnect event from NetworkManager
                if self.network.is_host and conn in self.client_conns:
                    pid = self.client_conns[conn]
                    print(f"Player {pid} disconnected.")
                    if pid in self.players:
                        del self.players[pid]
                    del self.client_conns[conn]
                    
                    # Notify everyone else
                    self.network.send({"type": "PLAYER_LEFT", "id": pid})

        # Game Logic
        if self.state == "GAME":
            # 1. Check if Game Over (All players dead)
            alive_players = [p for p in self.players.values() if p.alive]
            if not alive_players and not self.game_over:
                self.game_over = True

            local_player = self.players.get(self.local_id)
            keys = pygame.key.get_pressed()  # Get keys at GAME state level
            
            # 2. Spectator Logic & Camera
            if local_player and not local_player.alive and not self.game_over:
                # If we aren't spectating anyone or target is dead/gone, switch
                if not self.spectating_id or self.spectating_id not in self.players or not self.players[self.spectating_id].alive:
                    if alive_players:
                        self.spectating_id = alive_players[0].pid
                    else:
                        self.spectating_id = None # Should trigger game over logic above

                # Handle Spectator Switching (Left Click)
                if pygame.mouse.get_pressed()[0] and not self.shoot_pressed:
                     self.shoot_pressed = True
                     if alive_players:
                         # Find current index and cycle
                         current_ids = [p.pid for p in alive_players]
                         if self.spectating_id in current_ids:
                             idx = current_ids.index(self.spectating_id)
                             self.spectating_id = current_ids[(idx + 1) % len(current_ids)]
                         else:
                             self.spectating_id = current_ids[0]
                elif not pygame.mouse.get_pressed()[0]:
                     self.shoot_pressed = False

                # Camera follows target and uses target room for rendering
                if self.spectating_id and self.spectating_id in self.players:
                    target = self.players[self.spectating_id]
                    sw, sh = self.screen.get_size()
                    self.camera.x = target.rect.centerx - sw // 2
                    self.camera.y = target.rect.centery - sh // 2
                    # Update local "current room" for map rendering based on spectated player
                    self.current_room_coords = target.current_room_coords

            # 3. Alive Logic
            elif local_player and local_player.alive:
                self.spectating_id = None # Reset if we are alive
                
                # --- COLLISION LOGIC (Damage) ---
                hit_damage = 0
                
                # A. Bullet Collision (Enemy Bullets hitting Player)
                for b in self.bullets[:]:
                    # Check owner string to identify enemy bullets
                    if b.owner_id.startswith("enemy") or b.owner_id.startswith("boss"):
                        if local_player.rect.colliderect(b.rect):
                            hit_damage = 1
                            if b.bullet_type == "rocket": b.explode()
                            else: b.lifetime = 0 # Destroy bullet
                            break # Take one hit per frame max

                # B. Body Collision (Enemies touching Player) -> INSTANT KILL
                if hit_damage == 0:
                    for e in self.enemies.values():
                        # Simple circle/rect collision
                        dist = local_player.rect.centerx - e.rect.centerx, local_player.rect.centery - e.rect.centery
                        if (dist[0]**2 + dist[1]**2)**0.5 < (local_player.image_size/2 + e.size/2):
                            hit_damage = 5 # Instant kill amount
                            break

                # Heal Pickup Interaction
                for hpick in self.heal_pickups[:]:
                    hpick.update()
                    if hpick.room_coords == local_player.current_room_coords and hpick.rect.colliderect(local_player.rect):
                        if local_player.hp < local_player.max_hp:
                            healed = min(hpick.amount, local_player.max_hp - local_player.hp)
                            local_player.hp += healed
                            self._play_sfx("heal", room_coords=local_player.current_room_coords)
                            self.network.send({"type": "PLAYER_HEAL", "id": self.local_id, "amount": healed})
                        self.network.send({"type": "HEAL_PICKUP", "id": hpick.id})
                        self.heal_pickups = [h for h in self.heal_pickups if h.id != hpick.id]
                        break
                    
                    # Boss Body Collision
                    if hit_damage == 0:
                        for b in self.bosses.values():
                             if local_player.rect.colliderect(b.rect.inflate(-20, -20)):
                                 hit_damage = 5
                                 break

                # C. Beam Collision (THE SNIPER FIX)
                if hit_damage == 0:
                    for beam in self.beams:
                        # FIX 1: pygame.math.Vector2.rotate() takes DEGREES, not radians.
                        # The previous code converted to radians, causing the collision line 
                        # to point in the wrong direction.
                        
                        # Calculate beam end point based on start, length, and angle
                        beam_end = beam.start_pos + pygame.math.Vector2(beam.length, 0).rotate(-beam.angle)
                        
                        # FIX 2: Account for the Beam's width (40px)
                        # The collision check measures distance to the center line. 
                        # We need to trigger a hit if the player touches the EDGE of the beam.
                        beam_half_width = 20 
                        collision_radius = (local_player.image_size / 2) + beam_half_width
                        
                        # Check if player intersects with the thick beam line
                        if self._line_circle_collision(beam.start_pos, beam_end, local_player.rect.center, collision_radius):
                            print(f"BEAM HIT DETECTED! Applying damage")
                            hit_damage = 1 # Beam damage
                            break

                # Apply Damage
                if hit_damage > 0:
                    local_player.hp -= hit_damage
                    self._play_sfx("player_hit", room_coords=local_player.current_room_coords)
                    self.network.send({"type": "PLAYER_HIT", "id": self.local_id, "damage": hit_damage})
                    create_particles(local_player.rect.center, 20, RED, 2, 5, 20, 40)
                    
                    if local_player.hp <= 0:
                        local_player.hp = 0
                        local_player.alive = False
                        self._stop_all_weapon_sounds()
                        self.network.send({"type": "PLAYER_DEATH", "id": self.local_id})
                
                # ... (Rest of existing Weapon/Movement Logic) ...
                if local_player.weapon.last_shot_time > 0: local_player.weapon.last_shot_time -= 1
                local_player.weapon.update()
                
                mouse_pressed = pygame.mouse.get_pressed()
                
                # Get walls for collision
                if local_player.current_room_coords in self.dungeon:
                    curr_room = self.dungeon[local_player.current_room_coords]
                    walls = curr_room.get_walls()
                    if not curr_room.cleared and curr_room.enemies:
                        walls.extend(curr_room.get_doors())
                else:
                    walls = []

                # Rotate (pass walls to check collision after rotation)
                local_player.update_angle(self.camera, walls)

                # Handle burst fire timer
                weapon = local_player.weapon
                if weapon.burst_timer > 0:
                    weapon.burst_timer -= 1
                    if weapon.burst_timer <= 0 and weapon.current_burst > 0:
                        # Fire next burst bullet
                        sp = local_player.shoot_pos()
                        bullets_data = weapon.shoot(sp.x, sp.y, local_player.angle, 0)
                        for b_data in bullets_data:
                            # Determine bullet type based on weapon
                            btype = "normal"
                            if weapon.name == "Rocket":
                                btype = "rocket"
                            elif weapon.name == "SniperRifle":
                                btype = "sniper"
                            elif weapon.name == "GrenadeLauncher":
                                btype = "grenade"
                            elif weapon.name == "LaserRifle":
                                btype = "laser"
                            
                            self.network.send({
                                "type": "SHOOT", "id": self.local_id,
                                "x": b_data["x"], "y": b_data["y"],
                                "angle": b_data["angle"], "speed": b_data["speed"],
                                "btype": btype,
                                "wep": weapon.name,
                                "damage": b_data["damage"],
                                "color": BLUE
                            })
                            spawn_room = (int(b_data["x"] // ROOM_SIZE), int(b_data["y"] // ROOM_SIZE))
                            self.bullets.append(Bullet(b_data["x"], b_data["y"], b_data["angle"], self.local_id, b_data["speed"], BLUE, btype, b_data["damage"], spawn_room))
                        weapon.current_burst -= 1
                        if weapon.current_burst > 0:
                            weapon.burst_timer = weapon.burst_delay

                # Shooting - Click once for pistol/uzi burst, hold for other weapons
                can_shoot = False
                # Disable gameplay shooting when pause menu is open
                if not self.pause_menu_open and mouse_pressed[0]:
                    if weapon.name == "Pistol":
                        # Click-to-shoot with anti-autoclicker
                        if not self.shoot_pressed:
                            if weapon.last_click_time <= 0:
                                can_shoot = True
                                weapon.last_click_time = weapon.min_click_delay
                            self.shoot_pressed = True
                    elif weapon.name == "Uzi":
                        # Burst fire - click to start burst
                        # Added anti-spam delay
                        if not self.shoot_pressed and weapon.current_burst == 0:
                            if weapon.last_click_time <= 0:
                                can_shoot = True
                                weapon.last_click_time = weapon.min_click_delay
                            self.shoot_pressed = True
                    else:
                        # Hold for other weapons (Shotgun, Minigun, etc.)
                        can_shoot = True
                else:
                    self.shoot_pressed = False
                
                # Decrease anti-autoclicker timer
                if weapon.last_click_time > 0:
                    weapon.last_click_time -= 1

                # Minigun continuous sound management (local only)
                try:
                    if weapon.name == "Minigun":
                        ch = self.weapon_channels.get(self.local_id)
                        # Start loop if holding fire and not overheated
                        if mouse_pressed[0] and not weapon.overheated:
                            if not ch:
                                # Try to get the per-weapon sound, else fallback to generic
                                sound = self.weapon_sounds.get("Minigun") if hasattr(self, 'weapon_sounds') else None
                                if not sound:
                                    sound = self.sounds.get("minigun") or self.sounds.get("shot")
                                if sound:
                                    try:
                                        nch = pygame.mixer.find_channel(True)
                                        if nch:
                                            nch.set_volume(self.game_volume)
                                            nch.play(sound, loops=-1)
                                            self.weapon_channels[self.local_id] = nch
                                    except Exception:
                                        try:
                                            sound.play(-1)
                                        except Exception:
                                            pass
                        else:
                            # Stop loop when release or overheated
                            if ch:
                                try:
                                    ch.stop()
                                except Exception:
                                    pass
                                del self.weapon_channels[self.local_id]

                        # If weapon overheats while firing, stop the loop
                        if weapon.overheated:
                            ch2 = self.weapon_channels.get(self.local_id)
                            if ch2:
                                try:
                                    ch2.stop()
                                except Exception:
                                    pass
                                del self.weapon_channels[self.local_id]
                except Exception:
                    pass
                
                if can_shoot and weapon.last_shot_time <= 0 and weapon.current_burst == 0:
                     # Use shoot_pos for origin
                     sp = local_player.shoot_pos()
                     
                     bullets_data = weapon.shoot(sp.x, sp.y, local_player.angle, 0)
                     weapon.last_shot_time = weapon.get_current_cooldown()
                     # For Minigun don't trigger per-shot SFX; the continuous loop handles it
                     if weapon.name != "Minigun":
                         self._play_weapon_sfx(weapon.name, room_coords=local_player.current_room_coords)
                     
                     # Start burst if weapon has burst_count > 1
                     if weapon.burst_count > 1:
                         weapon.current_burst = weapon.burst_count - 1  # -1 because first shot already fired
                         weapon.burst_timer = weapon.burst_delay
                     
                     for b_data in bullets_data:
                         # Determine bullet type based on weapon
                         btype = "normal"
                         if weapon.name == "Rocket":
                             btype = "rocket"
                         elif weapon.name == "SniperRifle":
                             btype = "sniper"
                         elif weapon.name == "GrenadeLauncher":
                             btype = "grenade"
                         elif weapon.name == "LaserRifle":
                             btype = "laser" # New visual type maybe? Or just normal with high speed
                         
                         self.network.send({
                             "type": "SHOOT",
                             "id": self.local_id,
                             "x": b_data["x"],
                             "y": b_data["y"],
                             "angle": b_data["angle"],
                             "speed": b_data["speed"],
                             "btype": btype,
                             "wep": weapon.name,
                             "damage": b_data["damage"],
                             "color": BLUE
                         })
                         spawn_room = (int(b_data["x"] // ROOM_SIZE), int(b_data["y"] // ROOM_SIZE))
                         self.bullets.append(Bullet(b_data["x"], b_data["y"], b_data["angle"], self.local_id, b_data["speed"], BLUE, btype, b_data["damage"], spawn_room))
                
                # Chest Interaction
                if keys[pygame.K_e]:
                    # Find closest chest
                    for i, chest in enumerate(self.chests):
                        if not chest.opened and chest.rect.inflate(20,20).colliderect(local_player.rect):
                            chest.opened = True
                            self._play_sfx("chest_open", room_coords=local_player.current_room_coords)
                            # Spawn Dropped Weapon instead of auto-equipping
                            # Weighted Rarity
                            # Common: Shotgun, Uzi, Sniper, Rocket, LaserRifle, GrenadeLauncher, DualPistols (12-15% each)
                            # Rare: Minigun (8%)
                            # Super Rare (Troll): Pistol (2%)
                            wep_opts = ["Pistol", "Shotgun", "Uzi", "SniperRifle", "Minigun", "RocketLauncher", "LaserRifle", "GrenadeLauncher", "DualPistols"]
                            weights = [2, 14, 14, 14, 8, 14, 12, 12, 10]
                            new_wep_class = random.choices(wep_opts, weights=weights, k=1)[0]
                            drop_id = f"drop_{i}_{random.randint(0,999)}"
                            
                            # Spawn offset to be visible (random dir)
                            offset_x = random.choice([-50, 50])
                            offset_y = random.choice([-50, 50])
                            drop_x = chest.rect.centerx + offset_x
                            drop_y = chest.rect.centery + offset_y
                            
                            # Add local
                            self.dropped_weapons.append(DroppedWeapon(drop_id, new_wep_class, drop_x, drop_y, 30))
                            
                            self.network.send({"type": "CHEST_OPENED", "index": i})
                            self.network.send({
                                "type": "WEAPON_DROP", 
                                "id": drop_id, 
                                "class": new_wep_class, 
                                "x": drop_x, 
                                "y": drop_y
                            })
                            break
                            
                # Weapon Pickup Interaction
                for drop in self.dropped_weapons[:]:
                    drop.update()
                    if drop.pickup_cooldown <= 0 and drop.rect.colliderect(local_player.rect):
                        # Swap Weapons
                        old_weapon_class = local_player.weapon.name
                        if old_weapon_class == "Rocket": old_weapon_class = "RocketLauncher" # Fix naming mismatch if any
                        
                        # Equip New
                        # We use eval or a mapping. Safe mapping preferred but eval is quick for known classes.
                        # Known classes: Pistol, Uzi, Shotgun, SniperRifle, Minigun, RocketLauncher
                        weapon_map = {
                            "Pistol": Pistol, "Uzi": Uzi, "Shotgun": Shotgun, 
                            "SniperRifle": SniperRifle, "Minigun": Minigun, "Rocket": RocketLauncher, "RocketLauncher": RocketLauncher,
                            "LaserRifle": LaserRifle, "GrenadeLauncher": GrenadeLauncher, "DualPistols": DualPistols
                        }
                        
                        if drop.weapon_class_name in weapon_map:
                            local_player.weapon = weapon_map[drop.weapon_class_name]()
                            self._play_sfx("pickup", room_coords=local_player.current_room_coords)
                            
                            # Remove dropped item
                            if drop in self.dropped_weapons: self.dropped_weapons.remove(drop)
                            self.network.send({"type": "WEAPON_PICKUP", "id": drop.id})
                            
                            # Drop Old Weapon
                            old_drop_id = f"drop_{self.local_id}_{random.randint(0,9999)}"
                            # Drop slightly behind/away from player to avoid instant pickup confusion
                            # Just use small random offset
                            drop_off_x = random.randint(-60, 60)
                            drop_off_y = random.randint(-60, 60)
                            if abs(drop_off_x) < 30: drop_off_x = 40
                            if abs(drop_off_y) < 30: drop_off_y = 40
                            
                            dx = local_player.rect.centerx + drop_off_x
                            dy = local_player.rect.centery + drop_off_y
                            
                            new_drop = DroppedWeapon(old_drop_id, old_weapon_class, dx, dy, 60)
                            self.dropped_weapons.append(new_drop)
                            
                            self.network.send({
                                "type": "WEAPON_DROP",
                                "id": old_drop_id,
                                "class": old_weapon_class,
                                "x": dx,
                                "y": dy
                            })
                            break

                
                dx, dy = 0, 0
                if keys[pygame.K_w]: dy -= 1
                if keys[pygame.K_s]: dy += 1
                if keys[pygame.K_a]: dx -= 1
                if keys[pygame.K_d]: dx += 1
                
                # Normalize
                if dx != 0 or dy != 0:
                    mag = (dx*dx + dy*dy)**0.5
                    dx, dy = dx/mag, dy/mag
                
                # --- Dash Ability ---
                # Decrease dash timer
                if local_player.dash_timer > 0:
                    local_player.dash_timer -= 1
                
                # Handle ongoing dash
                if local_player.is_dashing:
                    local_player.dash_frames_left -= 1
                    if local_player.dash_frames_left <= 0:
                        local_player.is_dashing = False
                    else:
                        # Use stored dash direction with high speed
                        dx, dy = local_player.dash_direction
                        # Multiply by dash speed factor
                        original_speed = local_player.speed
                        local_player.speed = local_player.dash_speed
                        # (Will be restored after move call)
                
                # Trigger dash with SHIFT key
                if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]:
                    if local_player.dash_timer <= 0 and not local_player.is_dashing:
                        if dx != 0 or dy != 0:  # Only dash if moving
                            local_player.is_dashing = True
                            local_player.dash_frames_left = local_player.dash_duration
                            local_player.dash_timer = local_player.dash_cooldown
                            local_player.dash_direction = (dx, dy)
                            # Apply dash immediately this frame
                            original_speed = local_player.speed
                            local_player.speed = local_player.dash_speed
                
                # Simple Wall collision (Room boundaries)
                # Current Room Walls
                room = self.dungeon.get(local_player.current_room_coords)
                walls = [] 
                if room:
                    walls = room.get_walls()
                    doors = room.get_doors()
                    
                    # Calculate exploration percentage for boss door
                    total_rooms = len(self.dungeon)
                    explored_rooms = len(self.visited_rooms)
                    exploration_pct = explored_rooms / total_rooms if total_rooms > 0 else 0
                    boss_door_unlocked = exploration_pct >= 0.7
                    
                    # If room not cleared (enemies OR boss present), treat doors as walls (Locking)
                    boss_present = False
                    if room.type == ROOM_BOSS:
                         # Check if any boss is alive in this room
                         for b in self.bosses.values():
                             if b.room_coords == local_player.current_room_coords:
                                 boss_present = True
                                 break
                    
                    if (not room.cleared and room.enemies) or boss_present:
                         for d in doors:
                             walls.append(d)
                    
                    # Block boss door if not enough exploration
                    if not boss_door_unlocked:
                        for dir_name in ['N', 'S', 'E', 'W']:
                            if room.doors.get(dir_name):
                                adj_coords = list(local_player.current_room_coords)
                                if dir_name == 'N': adj_coords[1] -= 1
                                elif dir_name == 'S': adj_coords[1] += 1
                                elif dir_name == 'E': adj_coords[0] += 1
                                elif dir_name == 'W': adj_coords[0] -= 1
                                adj_room = self.dungeon.get(tuple(adj_coords))
                                if adj_room and adj_room.type == ROOM_BOSS:
                                    # Add ONLY the specific door leading to boss room
                                    r_rect = room.get_world_rect()
                                    door_size = 150
                                    thickness = 50
                                    if dir_name == 'N':
                                        boss_door_rect = pygame.Rect(r_rect.centerx - door_size//2, r_rect.top, door_size, thickness)
                                    elif dir_name == 'S':
                                        boss_door_rect = pygame.Rect(r_rect.centerx - door_size//2, r_rect.bottom - thickness, door_size, thickness)
                                    elif dir_name == 'W':
                                        boss_door_rect = pygame.Rect(r_rect.left, r_rect.centery - door_size//2, thickness, door_size)
                                    elif dir_name == 'E':
                                        boss_door_rect = pygame.Rect(r_rect.right - thickness, r_rect.centery - door_size//2, thickness, door_size)
                                    walls.append(boss_door_rect)
                    
                    # Check Room Transition
                    gx = int(local_player.rect.centerx // ROOM_SIZE)
                    gy = int(local_player.rect.centery // ROOM_SIZE)
                    if (gx, gy) != local_player.current_room_coords:
                         if (gx, gy) in self.dungeon:
                             local_player.current_room_coords = (gx, gy)
                             # Notify host about room entry (for enemy spawning)
                             self.network.send({"type": "ROOM_ENTER", "id": self.local_id, "room": (gx, gy)})
                             
                             # Host Logic: Broadcast discovery immediately when Host enters room
                             if self.network.is_host:
                                 self.network.send({"type": "ROOM_DISCOVERED", "coords": (gx, gy)})
                                 self.visited_rooms.add((gx, gy))
                             
                             # Push player inside room to avoid door clipping
                             new_room = self.dungeon[(gx, gy)]
                             nr_rect = new_room.get_world_rect()
                             # Push to center slightly
                             push_x = nr_rect.centerx
                             push_y = nr_rect.centery
                             # Move towards center by 100 pixels
                             dx_to_center = push_x - local_player.rect.centerx
                             dy_to_center = push_y - local_player.rect.centery
                             if abs(dx_to_center) > 50:
                                 local_player.rect.centerx += 70 if dx_to_center > 0 else -70
                             if abs(dy_to_center) > 50:
                                 local_player.rect.centery += 70 if dy_to_center > 0 else -70
                
                # Trapdoor collision - trigger level transition
                if self.trapdoor and self.trapdoor_room == local_player.current_room_coords:
                    if local_player.rect.colliderect(self.trapdoor):
                        if len(self.players) > 1:
                            # Multiplayer: request level transition
                            if not self.level_transition_pending:
                                self.level_transition_pending = True
                                self.level_transition_requester = self.local_id
                                self.level_transition_accepted.add(self.local_id)
                                self.network.send({"type": "LEVEL_REQUEST", "id": self.local_id})
                        else:
                            # Singleplayer: go directly to next level
                            self.floor_number += 1
                            new_seed = random.randint(10000, 99999)
                            new_color = self._pick_random_floor_color()
                            self._start_new_floor(new_seed, new_color)
                
                local_player.move(dx, dy, walls)
                
                # Restore speed after dash move
                if local_player.is_dashing or local_player.speed != 3.5:
                    local_player.speed = 3.5
                
                # Camera Follow (center player regardless of window size)
                sw, sh = self.screen.get_size()
                self.camera.x = local_player.rect.centerx - sw // 2
                self.camera.y = local_player.rect.centery - sh // 2
                self.current_room_coords = local_player.current_room_coords
                
                # Update Visited
                if local_player.current_room_coords not in self.visited_rooms:
                    self.visited_rooms.add(local_player.current_room_coords)

                # Send Network Update
                # Rate limit this? For now send every frame for smoothness test
                self.network.send({
                    "type": "PLAYER_UPDATE", 
                    "id": self.local_id, 
                    "pos": local_player.rect.center,
                    "angle": local_player.angle
                })
            
            # Update Bullets
            for b in self.bullets[:]:
                b.update()
                # Confine bullets to their spawn room
                b_room = (int(b.pos.x // ROOM_SIZE), int(b.pos.y // ROOM_SIZE))
                if b_room != b.spawn_room:
                    if b.bullet_type == "rocket" and not b.exploded:
                        b.explode()
                    b.lifetime = 0
                
                # Check wall collision
                # Need current room or nearby walls
                # Optimization: just check current player's room walls for now?
                # Or find room by bullet pos.
                # Simplification: Bullets die if outside room rect almost
                
                # Better: Check against walls of the room the bullet is in
                bgx = int(b.pos.x // ROOM_SIZE)
                bgy = int(b.pos.y // ROOM_SIZE)
                if (bgx, bgy) in self.dungeon:
                    broom = self.dungeon[(bgx, bgy)]
                    bwalls = broom.get_walls()
                    # Also check doors if locked? For bullets we might let them pass or hit doors.
                    # Let's say doors block bullets if locked.
                    if not broom.cleared and broom.enemies:
                        for d in broom.get_doors(): bwalls.append(d)
                        
                    for w in bwalls:
                        if b.rect.colliderect(w):
                            if getattr(b, 'bounces', 0) > 0:
                                b.bounces -= 1
                                # Simple reflection based on overlap
                                overlap_x = min(b.rect.right, w.right) - max(b.rect.left, w.left)
                                overlap_y = min(b.rect.bottom, w.bottom) - max(b.rect.top, w.top)
                                if overlap_x < overlap_y:
                                    b.velocity.x *= -1
                                    if b.rect.centerx < w.centerx: b.pos.x = w.left - b.rect.width/2
                                    else: b.pos.x = w.right + b.rect.width/2
                                else:
                                    b.velocity.y *= -1
                                    if b.rect.centery < w.centery: b.pos.y = w.top - b.rect.height/2
                                    else: b.pos.y = w.bottom + b.rect.height/2
                                b.rect.center = b.pos
                                continue

                            # Rocket/Grenade/Heal explodes on wall hit (or enemy hit logic below?)
                            # Actually this block is for WALLS. Heal bullets might pass through walls? 
                            # Usually heal bullets hit walls.
                            if b.bullet_type in ["rocket", "grenade", "heal"] and not b.exploded:
                                b.explode()
                                self.network.send({"type": "BULLET_EXPLODE", "id": b.owner_id if not hasattr(b, 'bullet_id') else b.bullet_id})
                                self._play_sfx("explosion", room_coords=(bgx, bgy))
                                # Damage nearby enemies in explosion radius (host only)
                                if self.network.is_host:
                                    for enemy in self.enemies.values():
                                        dist = pygame.math.Vector2(enemy.rect.center).distance_to(b.pos)
                                        if dist < b.explosion_radius:
                                            splash_dmg = 50 if b.bullet_type == "rocket" else 25
                                            enemy.hp -= splash_dmg
                            else:
                                b.lifetime = 0 # Kill normal bullet
                            break

                # Clean up bullets
                if b.exploded and b.explosion_timer <= 0:
                    self.bullets.remove(b)
                elif b.lifetime <= 0 and not b.exploded:
                    self.bullets.remove(b)

            # Client Visual Collision Prediction
            if not self.network.is_host:
                for b in self.bullets[:]:
                    if not b.exploded:
                        # Prevent enemies hitting themselves or each other visually
                        # Exception: Heal bullets target enemies
                        if b.owner_id.startswith("enemy") and b.bullet_type != "heal":
                            continue
                        
                        # Boss friendly fire check (Bosses don't hit turrets usually, but can hit others)
                        # For simplicity visually, let's assume boss bullets count against players mostly, 
                        # but if we want to show them hitting enemies (friendly fire), we allow it except for turrets maybe?
                        # Host logic: if b.owner_id.startswith("boss") and enemy.type == "turret": continue
                        
                        is_boss_bullet = b.owner_id.startswith("boss")

                        for enemy in self.enemies.values():
                            if is_boss_bullet and enemy.type == "turret":
                                continue

                            if enemy.rect.colliderect(b.rect):
                                # Visual Hit!
                                create_particles(b.rect.center, 5, YELLOW, 1, 3, 10, 20)
                                if b.bullet_type in ["rocket", "heal"]:
                                    b.explode()
                                else:
                                    if b in self.bullets: self.bullets.remove(b)
                                break # One enemy per bullet
                        
                        # Check Bosses
                        for boss in self.bosses.values():
                             # Ensure boss doesn't shoot itself
                             if b.owner_id == boss.bid: continue
                             
                             # Minions shouldn't hurt boss? usually yes.
                             if b.owner_id.startswith("enemy") and b.owner_id.replace("enemy_", "") in boss.minion_ids:
                                 continue

                             if boss.rect.colliderect(b.rect):
                                 create_particles(b.rect.center, 5, YELLOW, 1, 3, 10, 20)
                                 if b.bullet_type == "rocket":
                                     b.explode()
                                 else:
                                     if b in self.bullets: self.bullets.remove(b)
                                 break

            # Client Side Rocket Explosions (Visual Sync)
            # If a rocket explodes on host (deleted), client needs to know to explode it?
            # Current implementation: Client calculates collision locally for walls/enemies?
            # Enemies are synchronized by host updates.
            # WALL collisions should be consistent.
            # However, for smoothness, maybe clients should simulate explosion visual if they detect hit?
            # Added in collision loop above.
            
            # Update Beams
            for beam in self.beams[:]:
                # REMOVED: The logic that deleted the beam if its center wasn't in the spawn room.
                # Since beams are 2000px long, their center is often in a different room!
                
                if beam.update():  # Returns True when lifespan ends
                    self.beams.remove(beam)
            
            # Update Particles
            particles.update()
            
            # Handle Enemy beams (sniper creates beams)
            if self.network.is_host:
                for enemy in self.enemies.values():
                    if hasattr(enemy, 'pending_beam'):
                        pb = enemy.pending_beam
                        self.beams.append(EnergyBeam(pb["pos"], pb["angle"]))
                        del enemy.pending_beam
            
            # Host Logic: Update Enemies & Room State
            if self.network.is_host:
                dead_enemies = []
                
                # Check Room Activation
                for p in self.players.values():
                     r_coords = p.current_room_coords
                     if r_coords in self.dungeon:
                         curr_room = self.dungeon[r_coords]
                         if not curr_room.cleared and not curr_room.enemies:
                             # Spawn enemies on first entry, but with delay
                             if not hasattr(curr_room, 'has_spawned'):
                                 curr_room.spawn_enemies_for_room(self)
                                 curr_room.has_spawned = True
                                 curr_room.activation_timer = 60  # 1 second at 60fps
                                 curr_room.enemies = [e for e in self.enemies.values() if e.room_coords == r_coords]
                                 # Freeze enemies until timer expires
                                 for e in curr_room.enemies:
                                     e.frozen = True
                         
                         # Count down activation timer
                         if hasattr(curr_room, 'activation_timer') and curr_room.activation_timer > 0:
                             curr_room.activation_timer -= 1
                             if curr_room.activation_timer <= 0:
                                 # Unfreeze enemies
                                 for e in self.enemies.values():
                                     if e.room_coords == r_coords:
                                         e.frozen = False
                
                # Update Enemies
                for enemy in self.enemies.values():
                    enemy.update_host(self.players, self.dungeon, self.network, self.bullets, self)

                    # Check collisions with bullets
                    for b in self.bullets[:]:
                        b_room = (int(b.pos.x // ROOM_SIZE), int(b.pos.y // ROOM_SIZE))
                        if enemy.room_coords and b_room != enemy.room_coords:
                            continue

                        # Boss Friendly Fire Check: Boss bullets don't hurt Turrets
                        if b.owner_id.startswith("boss") and enemy.type == "turret":
                            continue

                        is_owner = (b.owner_id == enemy.eid) or b.owner_id.startswith(f"enemy_{enemy.eid}_")
                        if not is_owner and not b.exploded:
                            # Allow collision if it's a player bullet OR if it's a healing bullet (even from enemy)
                            if not b.owner_id.startswith("enemy") or b.bullet_type == "heal":
                                if enemy.rect.colliderect(b.rect):
                                    # Phaser invulnerability
                                    if enemy.type == "phaser" and getattr(enemy, "is_phased", False):
                                        continue
                                    
                                    # Shielder blocking
                                    if enemy.type == "shielder":
                                        # Calculate angle from enemy to bullet
                                        bullet_dir = b.pos - enemy.pos
                                        if bullet_dir.length() > 0:
                                            bullet_angle = math.degrees(math.atan2(-bullet_dir.y, bullet_dir.x))
                                            # Check if bullet is within shield arc (90 degrees)
                                            angle_diff = (bullet_angle - enemy.shield_angle + 180) % 360 - 180
                                            if abs(angle_diff) < 45:
                                                # Blocked!
                                                create_particles(b.rect.center, 5, BLUE, 1, 3, 10, 20)
                                                if b.bullet_type in ["rocket", "grenade"]:
                                                    b.explode()
                                                    if b in self.bullets: self.bullets.remove(b) # Remove grenade on block too
                                                else:
                                                    if b in self.bullets: self.bullets.remove(b)
                                                continue

                                    # Healing logic
                                    if b.bullet_type == "heal":
                                        enemy.hp = min(enemy.hp + 5, 100) # Heal 5 hp
                                        b.explode() # Show particles on Host
                                        # Broadcast explosion so clients show particles/remove bullet
                                        self.network.send({"type": "BULLET_EXPLODE", "id": b.owner_id if not hasattr(b, 'bullet_id') else b.bullet_id})
                                        continue

                                    # Determine damage based on bullet type
                                    damage = b.damage
                                    # Use bullet damage which is now accurate per weapon
                                    
                                    enemy.hp -= damage
                                    self._play_sfx("enemy_hit", room_coords=enemy.room_coords)
                                    
                                    # Rocket/Grenade explosion - damage all enemies in radius
                                    if b.bullet_type in ["rocket", "grenade"]:
                                        b.explode()
                                        self.network.send({"type": "BULLET_EXPLODE", "id": b.owner_id if not hasattr(b, 'bullet_id') else b.bullet_id})
                                        # Damage nearby enemies
                                        for other_enemy in self.enemies.values():
                                            if other_enemy.eid != enemy.eid:
                                                if other_enemy.room_coords and b_room != other_enemy.room_coords:
                                                    continue
                                                dist = pygame.math.Vector2(other_enemy.rect.center).distance_to(b.pos)
                                                if dist < b.explosion_radius:
                                                    splash_dmg = 50 if b.bullet_type == "rocket" else 25
                                                    other_enemy.hp -= splash_dmg
                                                    if other_enemy.hp <= 0:
                                                        dead_enemies.append(other_enemy.eid)
                                        # Remove grenade/rocket after explosion logic
                                        if b in self.bullets: self.bullets.remove(b)
                                    else:
                                        if b in self.bullets: self.bullets.remove(b)
                                    
                                    if enemy.hp <= 0:
                                        dead_enemies.append(enemy.eid)
                    
                    payload = {
                        "type": "ENEMY_UPDATE",
                        "id": enemy.eid,
                        "pos": enemy.rect.center,
                        "etype": enemy.type,
                        "speed": 8 # Default speed sync for late joiners (safe fallback)
                    }
                    if enemy.type == "tank": payload["speed"] = 7
                    elif enemy.type == "turret": payload["speed"] = 6
                    
                    # Send sniper laser target if exists
                    if enemy.type == "sniper" and hasattr(enemy, 'laser_target') and enemy.laser_target:
                        payload["laser_target"] = enemy.laser_target
                    
                    if enemy.type == "shielder":
                        payload["shield_angle"] = enemy.shield_angle
                    
                    if enemy.type == "phaser":
                        payload["is_phased"] = enemy.is_phased
                        
                    self.network.send(payload)
                    
                    # Lifespan/General Death Check (Outside bullet loop)
                    if enemy.hp <= 0:
                        dead_enemies.append(enemy.eid)
                
                for eid in set(dead_enemies): # set to avoid double kill logic if multiple bullets hit
                     if eid in self.enemies:
                         enemy = self.enemies[eid]
                         r_coords = enemy.room_coords
                         
                         # Death particles
                         create_particles(enemy.rect.center, 20, enemy.color, 2, 8, 20, 50)
                         
                         # Splitter splits into 2 chargers
                         if enemy.type == "splitter":
                             for _ in range(2):
                                 offset_x = random.randint(-30, 30)
                                 offset_y = random.randint(-30, 30)
                                 self.spawn_enemy(enemy.pos.x + offset_x, enemy.pos.y + offset_y, "charger", r_coords)
                         
                         del self.enemies[eid]
                         self._play_sfx("enemy_death", room_coords=r_coords)
                         self.network.send({"type": "ENEMY_DEATH", "id": eid})

                         if random.random() < 0.12 and r_coords is not None:
                             hid = f"heal_{random.randint(0, 9999999)}"
                             hx, hy = enemy.rect.centerx, enemy.rect.centery
                             pickup = HealPickup(hid, hx, hy, 1, r_coords)
                             self.heal_pickups.append(pickup)
                             self.network.send({"type": "HEAL_DROP", "id": hid, "x": hx, "y": hy, "amount": 1, "room": r_coords})
                         
                         # Check Room Clear
                         if r_coords:
                             # Count remaining in that room (enemies + bosses)
                             remaining_e = [e for e in self.enemies.values() if e.room_coords == r_coords]
                             remaining_b = [b for b in self.bosses.values() if b.room_coords == r_coords]
                             if not remaining_e and not remaining_b:
                                 if r_coords in self.dungeon:
                                     self.dungeon[r_coords].cleared = True
                                     self.network.send({"type": "ROOM_CLEARED", "coords": r_coords})
                
                # Update Bosses
                dead_bosses = []
                for boss in self.bosses.values():
                    boss.update_host(self.players, self.dungeon, self.network, self.bullets, self)
                    
                    # Check collisions with bullets
                    for b in self.bullets[:]:
                        b_room = (int(b.pos.x // ROOM_SIZE), int(b.pos.y // ROOM_SIZE))
                        if boss.room_coords and b_room != boss.room_coords:
                            continue

                        if not b.owner_id.startswith("boss"):
                            # Check if bullet matches any of this boss's minions
                            is_minion_shot = False
                            # Turrets shoot with owner_id "enemy_{eid}"
                            # Minion IDs list has just "{eid}"
                            bullet_source_id = b.owner_id.replace("enemy_", "")
                            if bullet_source_id in boss.minion_ids:
                                is_minion_shot = True
                            
                            if not is_minion_shot and boss.rect.colliderect(b.rect):
                                # Healing check
                                if b.bullet_type == "heal":
                                    boss.hp = min(boss.hp + 10, boss.max_hp)
                                    create_particles(boss.rect.center, 15, GREEN, 1, 4, 15, 30)
                                    if b in self.bullets: self.bullets.remove(b)
                                    continue

                                if b.bullet_type in ["rocket", "grenade"]:
                                    if (not b.exploded) and (boss.bid not in b.hit_ids):
                                        b.hit_ids.add(boss.bid)
                                        boss.hp -= b.damage
                                        create_particles(b.rect.center, 5, YELLOW, 1, 3, 10, 20)
                                        if b.explode():
                                            for minion_id in boss.minion_ids:
                                                if minion_id in self.enemies:
                                                    m = self.enemies[minion_id]
                                                    dist = m.pos.distance_to(b.pos)
                                                    if dist < b.explosion_radius:
                                                        splash = 50 if b.bullet_type == "rocket" else 25
                                                        m.hp -= splash
                                                        if m.hp <= 0:
                                                            pass
                                else:
                                    boss.hp -= b.damage
                                    create_particles(b.rect.center, 5, YELLOW, 1, 3, 10, 20)
                                    if b in self.bullets: self.bullets.remove(b)
                                
                                if boss.hp <= 0:
                                    dead_bosses.append(boss.bid)
                    
                    self.network.send({
                        "type": "BOSS_UPDATE",
                        "id": boss.bid,
                        "pos": boss.rect.center,
                        "hp": boss.hp,
                        "laser_target": boss.laser_target if getattr(boss, 'laser_target', None) else None
                    })
                
                for bid in set(dead_bosses):
                    if bid in self.bosses:
                        boss = self.bosses[bid]
                        self._play_sfx("explosion", room_coords=boss.room_coords)
                        create_particles(boss.rect.center, 100, boss.color, 3, 10, 40, 80)
                        r_coords = boss.room_coords
                        del self.bosses[bid]
                        self.network.send({"type": "BOSS_DEATH", "id": bid})
                        
                        # Increment boss kills for progressive difficulty
                        self.boss_kills_total += 1

                        # If Summoner, kill all summoned minions upon death
                        if boss.variant == "summoner":
                            for minion_id in boss.minion_ids:
                                if minion_id in self.enemies:
                                    # Create particles for visual feedback
                                    m_death = self.enemies[minion_id]
                                    create_particles(m_death.rect.center, 20, m_death.color, 2, 8, 20, 50)
                                    del self.enemies[minion_id]
                                    self.network.send({"type": "ENEMY_DEATH", "id": minion_id})
                        
                        # Check Room Clear
                        if r_coords:
                            remaining_e = [e for e in self.enemies.values() if e.room_coords == r_coords]
                            remaining_b = [b for b in self.bosses.values() if b.room_coords == r_coords]
                            if not remaining_e and not remaining_b:
                                if r_coords in self.dungeon:
                                    self.dungeon[r_coords].cleared = True
                                    self.network.send({"type": "ROOM_CLEARED", "coords": r_coords})
                                    
                                    # Spawn trapdoor at room center
                                    room_rect = self.dungeon[r_coords].get_world_rect()
                                    self.trapdoor = pygame.Rect(room_rect.centerx - 40, room_rect.centery - 40, 80, 80)
                                    self.trapdoor_room = r_coords
                                    self.network.send({"type": "TRAPDOOR_SPAWN", "x": self.trapdoor.x, "y": self.trapdoor.y, "room": r_coords})

            # Helper for manual testing enemies
            if self.network.is_host and keys[pygame.K_t]:
                if self.enemy_counter < 5: self.spawn_enemy(400, 400, "shooter")

    def draw(self):
        self.screen.fill(BLACK)

        if self.state == "SPLASH":
            sw, sh = self.screen.get_size()
            self.screen.fill((0, 0, 0))
            if self.splash_image and self.splash_rect:
                elapsed = pygame.time.get_ticks() - self.splash_start_time
                alpha = 255
                if elapsed < self.fade_in_duration:
                    alpha = int(255 * (elapsed / self.fade_in_duration))
                elif elapsed > (self.splash_duration - self.fade_out_duration):
                    alpha = int(255 * ((self.splash_duration - elapsed) / self.fade_out_duration))
                temp = self.splash_image.copy()
                temp.set_alpha(max(0, min(255, alpha)))
                self.splash_rect.center = (sw // 2, sh // 2)
                self.screen.blit(temp, self.splash_rect)
            pygame.display.flip()
            return
        
        if self.state == "MENU":
            sw, sh = self.screen.get_size()
            layout = self._get_menu_layout()

            # Space background
            self._draw_menu_starfield()

            # Title image at top-center
            if self.title_image is not None:
                max_w = int(sw * 0.96)
                max_h = int(sh * 0.34)
                base_w, base_h = self.title_image.get_size()
                scale = min(max_w / base_w, max_h / base_h)
                new_size = (max(1, int(base_w * scale)), max(1, int(base_h * scale)))
                if self.title_image_scaled is None or self.title_image_scaled_size != new_size:
                    self.title_image_scaled = pygame.transform.smoothscale(self.title_image, new_size)
                    self.title_image_scaled_size = new_size
                img_rect = self.title_image_scaled.get_rect(center=(sw // 2, int(sh * 0.15)))
                self.screen.blit(self.title_image_scaled, img_rect)
            else:
                self.draw_text("Roomarow", (sw // 2, int(sh * 0.16)), WHITE, size=84)

            # Username input box
            name_rect = self._get_name_input_rect()
            pygame.draw.rect(self.screen, (30, 30, 40), name_rect, border_radius=10)
            pygame.draw.rect(self.screen, WHITE if self.name_input_active else (150, 150, 150), name_rect, 2, border_radius=10)
            self.draw_text(f"Username: {self.local_name}", name_rect.center, self.local_name_color, size=30)
            self.draw_text("(Click box to type. TAB changes color)", (sw // 2, name_rect.bottom + 18), (200, 200, 200), size=22)

            # Buttons
            mouse_pos = pygame.mouse.get_pos()

            if self.menu_screen == "MAIN":
                for label, rect in layout["main"].items():
                    self._draw_menu_button(rect, label, rect.collidepoint(mouse_pos))
            elif self.menu_screen == "CUSTOM":
                self.draw_text("CUSTOM GAME", (sw // 2, int(sh * 0.36)), WHITE, size=44)
                
                # Draw Floor Selector
                floor_rect = pygame.Rect(sw // 2 - 100, layout["custom"]["FloorDown"].top, 200, 40)
                self.draw_text(f"Floor: {self.custom_floor}", floor_rect.center, WHITE, size=30)
                self._draw_menu_button(layout["custom"]["FloorDown"], "<", layout["custom"]["FloorDown"].collidepoint(mouse_pos))
                self._draw_menu_button(layout["custom"]["FloorUp"], ">", layout["custom"]["FloorUp"].collidepoint(mouse_pos))
                
                # Draw Weapon Selector
                wep_rect = pygame.Rect(sw // 2 - 100, layout["custom"]["WeaponDown"].top, 200, 40)
                self.draw_text(f"Weapon: {self.available_weapons[self.custom_weapon_idx]}", wep_rect.center, WHITE, size=30)
                self._draw_menu_button(layout["custom"]["WeaponDown"], "<", layout["custom"]["WeaponDown"].collidepoint(mouse_pos))
                self._draw_menu_button(layout["custom"]["WeaponUp"], ">", layout["custom"]["WeaponUp"].collidepoint(mouse_pos))
                
                self._draw_menu_button(layout["custom"]["Start"], "Start", layout["custom"]["Start"].collidepoint(mouse_pos))
                self._draw_menu_button(layout["custom"]["Back"], "Back", layout["custom"]["Back"].collidepoint(mouse_pos))

            elif self.menu_screen == "MULTIPLAYER":
                self.draw_text("MULTIPLAYER", (sw // 2, int(sh * 0.36)), WHITE, size=44)
                for label, rect in layout["multiplayer"].items():
                    self._draw_menu_button(rect, label, rect.collidepoint(mouse_pos))
            elif self.menu_screen == "SETTINGS":
                self.draw_text("SETTINGS", (sw // 2, int(sh * 0.36)), WHITE, size=44)
                fullscreen_label = "Fullscreen: On" if self.fullscreen else "Fullscreen: Off"
                self._draw_menu_button(layout["settings"]["Fullscreen"], fullscreen_label, layout["settings"]["Fullscreen"].collidepoint(mouse_pos))
                
                # Game Volume Slider
                gv_rect = layout["settings"]["GameVolume"]
                self._draw_volume_slider(gv_rect, "Game Volume", self.game_volume)
                
                # Music Volume Slider
                musv_rect = layout["settings"]["MusicVolume"]
                self._draw_volume_slider(musv_rect, "Music Volume", self.music_volume)

                self._draw_menu_button(layout["settings"]["Back"], "Back", layout["settings"]["Back"].collidepoint(mouse_pos))
            elif self.menu_screen == "JOIN_IP":
                self.draw_text("ENTER HOST IP", (sw // 2, int(sh * 0.36)), WHITE, size=44)

                ip_rect = layout["join_ip"]["InputBox"]
                pygame.draw.rect(self.screen, (30, 30, 40), ip_rect, border_radius=10)
                pygame.draw.rect(self.screen, WHITE, ip_rect, 2, border_radius=10)

                display_ip = self._sanitize_ip_text(self.join_ip) if self.join_ip else ""
                if (pygame.time.get_ticks() // 500) % 2 == 0:
                    display_ip += "|"
                self.draw_text(display_ip, ip_rect.center, WHITE, size=32)

                self._draw_menu_button(layout["join_ip"]["Connect"], "Connect", layout["join_ip"]["Connect"].collidepoint(mouse_pos))
                self._draw_menu_button(layout["join_ip"]["Back"], "Back", layout["join_ip"]["Back"].collidepoint(mouse_pos))
            
        elif self.state == "LOBBY":
            sw, sh = self.screen.get_size()

            overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
            overlay.fill((10, 15, 20, 200))
            self.screen.blit(overlay, (0, 0))

            panel_rect = pygame.Rect(40, 40, 400, sh - 80)
            pygame.draw.rect(self.screen, (30, 30, 35), panel_rect, border_radius=15)
            pygame.draw.rect(self.screen, (100, 100, 120), panel_rect, 2, border_radius=15)

            self.draw_text("SQUAD LIST", (panel_rect.centerx, panel_rect.top + 40), (200, 200, 255), size=40)
            pygame.draw.line(self.screen, (100, 100, 120), (panel_rect.left + 20, panel_rect.top + 70), (panel_rect.right - 20, panel_rect.top + 70), 2)

            y_offset = panel_rect.top + 100
            all_players = list(self.players.values())
            if self.local_id not in self.players:
                self.draw_text(f"{self.local_name} (YOU)", (panel_rect.centerx, y_offset), self.local_name_color, size=32)
                y_offset += 50

            for p in all_players:
                p_name = p.name
                if p.pid == self.local_id:
                    p_name += " (YOU)"
                if p.pid == "HOST" or (self.network.is_host and p.pid == self.local_id):
                    p_name += " [HOST]"
                self.draw_text(p_name, (panel_rect.centerx, y_offset), p.name_color, size=32)
                y_offset += 50

            if self.network.is_host:
                btn_rect = pygame.Rect(sw - 220, sh - 80, 200, 60)
                back_rect = pygame.Rect(sw - 220, 40, 200, 60)
                mx, my = pygame.mouse.get_pos()
                col = (50, 200, 50) if btn_rect.collidepoint((mx, my)) else (30, 150, 30)
                pygame.draw.rect(self.screen, col, btn_rect, border_radius=10)
                pygame.draw.rect(self.screen, WHITE, btn_rect, 2, border_radius=10)
                self.draw_text("START OP", btn_rect.center, WHITE, size=32)
                self.draw_text("Waiting for squad...", (sw - 220 + 100, sh - 120), (180, 180, 180), size=24)

                bcol = (90, 90, 110) if back_rect.collidepoint((mx, my)) else (60, 60, 80)
                pygame.draw.rect(self.screen, bcol, back_rect, border_radius=10)
                pygame.draw.rect(self.screen, WHITE, back_rect, 2, border_radius=10)
                self.draw_text("BACK", back_rect.center, WHITE, size=28)
            else:
                back_rect = pygame.Rect(sw - 220, 40, 200, 60)
                self.draw_text("WAITING FOR HOST...", (sw - 200, sh - 80), (200, 200, 200), size=36)
                pulse = (pygame.time.get_ticks() // 10) % 255
                loader_rect = pygame.Rect(sw - 220, sh - 150, 40, 40)
                pygame.draw.rect(self.screen, (pulse, pulse, pulse), loader_rect, 2)

                mx, my = pygame.mouse.get_pos()
                bcol = (90, 90, 110) if back_rect.collidepoint((mx, my)) else (60, 60, 80)
                pygame.draw.rect(self.screen, bcol, back_rect, border_radius=10)
                pygame.draw.rect(self.screen, WHITE, back_rect, 2, border_radius=10)
                self.draw_text("BACK", back_rect.center, WHITE, size=28)
            
        elif self.state == "GAME":
            # Fill with void color (Grid color from Arow.py)
            self.screen.fill(GRID_COLOR)
            
            local_player = self.players.get(self.local_id)
            # Use spectated player's room when dead and spectating
            if local_player and not local_player.alive and self.spectating_id and self.spectating_id in self.players:
                current_coords = self.players[self.spectating_id].current_room_coords
            else:
                current_coords = local_player.current_room_coords if local_player else (0, 0)
            
            # Draw World - ONLY current room visible
            if self.dungeon and current_coords in self.dungeon:
                room = self.dungeon[current_coords]
                r_rect = room.get_world_rect()
                draw_rect = r_rect.move(-self.camera.x, -self.camera.y)
                
                # Draw Floor (Dynamic Dark Color)
                pygame.draw.rect(self.screen, self.floor_color, draw_rect)
                
                # Generate floor rocks if not yet generated
                if not room.floor_rocks:
                    for _ in range(20):  # 20 random rocks/details
                        rx = random.randint(r_rect.left + 80, r_rect.right - 80)
                        ry = random.randint(r_rect.top + 80, r_rect.bottom - 80)
                        rsize = random.randint(3, 8)
                        rcolor = random.choice([(40,40,45), (35,35,40), (50,50,55), (45,42,40)])
                        room.floor_rocks.append((rx, ry, rsize, rcolor))
                
                # Draw rocks after floor, before doors/walls
                for (rx, ry, rsize, rcolor) in room.floor_rocks:
                    dr_x = rx - self.camera.x
                    dr_y = ry - self.camera.y
                    pygame.draw.circle(self.screen, rcolor, (int(dr_x), int(dr_y)), rsize)

                # Draw Doors (Before Walls)
                doors = room.get_doors()
                
                # Check if boss door should be locked (need 70% exploration)
                total_rooms = len(self.dungeon)
                explored_rooms = len(self.visited_rooms)
                exploration_pct = explored_rooms / total_rooms if total_rooms > 0 else 0
                boss_door_unlocked = exploration_pct >= 0.7
                
                # Identify available directions in the order get_doors returns them (N, S, W, E)
                available_dirs = []
                if room.doors.get('N'): available_dirs.append('N')
                if room.doors.get('S'): available_dirs.append('S')
                if room.doors.get('W'): available_dirs.append('W')
                if room.doors.get('E'): available_dirs.append('E')
                
                for dir_name, d in zip(available_dirs, doors):
                    dr = d.move(-self.camera.x, -self.camera.y)
                    
                    # Check if this door leads to boss room
                    adj_coords = list(current_coords)
                    if dir_name == 'N': adj_coords[1] -= 1
                    elif dir_name == 'S': adj_coords[1] += 1
                    elif dir_name == 'E': adj_coords[0] += 1
                    elif dir_name == 'W': adj_coords[0] -= 1
                    adj_room = self.dungeon.get(tuple(adj_coords))
                    
                    is_boss_door = adj_room and adj_room.type == ROOM_BOSS
                    
                    if is_boss_door:
                        if boss_door_unlocked:
                            pygame.draw.rect(self.screen, PURPLE, dr)  # Unlocked boss door
                        else:
                            pygame.draw.rect(self.screen, (80, 0, 80), dr)  # Locked boss door (dark purple)
                            # Draw lock indicator
                            pct_text = f"{int(exploration_pct*100)}%"
                    elif (not room.cleared and room.enemies) or (room.type == ROOM_BOSS and not room.cleared):
                        # Use updated logic to check if actually locked due to boss presence
                        # Visual simplification: if boss room and not cleared, render red.
                        # Real logic checked bosses list, but for drawing red door it is safe enough.
                        # Actually let's be consistent with collision logic:
                        is_locked = False
                        if room.enemies: is_locked = True
                        if room.type == ROOM_BOSS:
                             for b in self.bosses.values():
                                 if b.room_coords == current_coords:
                                     is_locked = True
                                     break
                                     
                        if is_locked:
                             pygame.draw.rect(self.screen, RED, dr) 
                        else:
                             pygame.draw.rect(self.screen, self.floor_color, dr)
                    else:
                        pygame.draw.rect(self.screen, self.floor_color, dr)

                # Draw Dropped Weapons
                for drop in self.dropped_weapons:
                    drop_room = (int(drop.pos.x // ROOM_SIZE), int(drop.pos.y // ROOM_SIZE))
                    if drop_room == current_coords:
                        drop.draw(self.screen, self.camera, self.font)

                for hpick in self.heal_pickups:
                    if hpick.room_coords == current_coords:
                        hpick.draw(self.screen, self.camera, self.font)

                # Draw Walls with Parallax 3D Effect
                # Sort walls by Y mainly to help painter's algorithm
                walls = room.get_walls()
                walls.sort(key=lambda w: w.centery)
                
                # Use current window size for parallax center so fullscreen/windowed both look correct
                sw, sh = self.screen.get_size()
                screen_center = pygame.math.Vector2(sw // 2, sh // 2)
                
                # Pre-calculate wall data to split drawing into two passes
                # Pass 1: Draw ALL sides (shading)
                # Pass 2: Draw ALL tops
                # This ensures the "light top side" is ALWAYS on top of any shading, as requested.
                
                def calculate_wall_data(rect):
                    base_rect = rect.move(-self.camera.x, -self.camera.y)
                    corners_base = [
                        pygame.math.Vector2(base_rect.topleft), 
                        pygame.math.Vector2(base_rect.topright), 
                        pygame.math.Vector2(base_rect.bottomright), 
                        pygame.math.Vector2(base_rect.bottomleft)
                    ]
                    
                    corners_top = []
                    parallax_factor = 0.15
                    
                    for p in corners_base:
                        vec_to_center = p - screen_center
                        offset_x = vec_to_center.x * parallax_factor
                        offset_y = vec_to_center.y * parallax_factor
                        corners_top.append(pygame.math.Vector2(p.x + offset_x, p.y + offset_y))
                        
                    return base_rect, corners_base, corners_top

                def draw_wall_sides(base_rect, corners_base, corners_top, color_base):
                     side_color = (max(0, color_base[0]-30), max(0, color_base[1]-30), max(0, color_base[2]-30))
                     vec_to_center = screen_center - pygame.math.Vector2(base_rect.center)
                     
                     # Backface culling checks
                     if vec_to_center.y < 0: # Top
                         pygame.draw.polygon(self.screen, side_color, [corners_base[0], corners_base[1], corners_top[1], corners_top[0]])
                     if vec_to_center.x > 0: # Right
                         pygame.draw.polygon(self.screen, side_color, [corners_base[1], corners_base[2], corners_top[2], corners_top[1]])
                     if vec_to_center.y > 0: # Bottom
                         pygame.draw.polygon(self.screen, side_color, [corners_base[2], corners_base[3], corners_top[3], corners_top[2]])
                     if vec_to_center.x < 0: # Left
                         pygame.draw.polygon(self.screen, side_color, [corners_base[3], corners_base[0], corners_top[0], corners_top[3]])

                def draw_wall_top(corners_top, color_top):
                    pygame.draw.polygon(self.screen, color_top, corners_top)
                    pygame.draw.polygon(self.screen, (color_top[0]//2, color_top[1]//2, color_top[2]//2), corners_top, 1)

                wall_data_list = [calculate_wall_data(w) for w in walls]

                # Pass 1: Sides
                for data in wall_data_list:
                    draw_wall_sides(data[0], data[1], data[2], DARK_GRAY)
                    
                # Pass 2: Tops
                for data in wall_data_list:
                    draw_wall_top(data[2], (60, 60, 65))
            
            # Draw Bosses
            for boss in self.bosses.values():
                if boss.room_coords == current_coords:
                    boss.draw(self.screen, self.camera)
            
            # Draw Enemies
            for e in self.enemies.values():
                if e.room_coords == current_coords:
                    e.draw(self.screen, self.camera)

            # Draw Beams
            for beam in self.beams[:]:
                # Use spawn_room instead of calculating room from center
                # This ensures if we are in the room where the sniper fired, we see the beam
                if beam.spawn_room == current_coords:
                    beam.draw(self.screen, self.camera)
            
            # Draw Particles
            for particle in particles:
                pr_room = (int(particle.rect.centerx // ROOM_SIZE), int(particle.rect.centery // ROOM_SIZE))
                if pr_room == current_coords:
                    dr = particle.rect.move(-self.camera.x, -self.camera.y)
                    self.screen.blit(particle.image, dr)

            # Draw Players (Only ALIVE ones)
            for p in self.players.values():
                if p.alive and p.current_room_coords == current_coords: # Check alive
                    image_rect = p.image.get_rect(center=p.rect.center)
                    draw_rect = image_rect.move(-self.camera.x, -self.camera.y)
                    self.screen.blit(p.image, draw_rect)
                    if hasattr(p, 'name'):
                        txt = self.font.render(p.name, True, p.name_color)
                        name_x = p.rect.centerx - self.camera.x
                        name_y = p.rect.top - 20 - self.camera.y
                        txt_rect = txt.get_rect(center=(name_x, name_y))
                        self.screen.blit(txt, txt_rect)
            
            # Draw Bullets
            for b in self.bullets:
                b_room = (int(b.pos.x // ROOM_SIZE), int(b.pos.y // ROOM_SIZE))
                if b_room == current_coords:
                    b.draw(self.screen, self.camera)
            
            # Draw Chests
            for c in self.chests:
                c_room = (int(c.rect.centerx // ROOM_SIZE), int(c.rect.centery // ROOM_SIZE))
                if c_room == current_coords:
                    c.draw(self.screen, self.camera)

            # Draw HUD
            local_player = self.players.get(self.local_id)
            
            # --- HEALTH BAR UI ---
            if local_player and local_player.alive:
                # Draw Hearts/Bar at top left
                bar_x, bar_y = 20, 20
                heart_size = 20
                gap = 5
                
                # Draw Background Bar
                # pygame.draw.rect(self.screen, BLACK, (bar_x - 5, bar_y - 5, (heart_size+gap)*5 + 10, heart_size + 10), border_radius=5)
                
                for i in range(local_player.max_hp):
                    x = bar_x + i * (heart_size + gap)
                    color = RED if i < local_player.hp else (50, 0, 0) # Bright red for health, dark for empty
                    # Draw Heart shape (triangle + circles) or just Rect for simplicity
                    pygame.draw.rect(self.screen, color, (x, bar_y, heart_size, heart_size))
                
                # Weapon Info
                hud_text = f"Weapon: {local_player.weapon.name} | Floor: {self.floor_number}"
                hud_font = pygame.font.Font(None, 24)
                hud_w, hud_h = hud_font.size(hud_text)
                hud_x = bar_x
                hud_y = bar_y + heart_size + 18
                self.draw_text(hud_text, (hud_x + hud_w // 2, hud_y + hud_h // 2), size=24)
                
                # --- Dash Cooldown UI ---
                dash_ui_x = bar_x
                dash_ui_y = hud_y + 30
                dash_bar_width = 100
                dash_bar_height = 12
                
                # Draw background bar
                pygame.draw.rect(self.screen, (30, 30, 40), (dash_ui_x, dash_ui_y, dash_bar_width, dash_bar_height), border_radius=4)
                
                if local_player.dash_timer <= 0:
                    # Dash ready - show full green bar
                    pygame.draw.rect(self.screen, (50, 200, 100), (dash_ui_x, dash_ui_y, dash_bar_width, dash_bar_height), border_radius=4)
                    dash_label = "DASH [SHIFT]"
                    dash_color = (100, 255, 150)
                else:
                    # Dash on cooldown - show progress bar
                    cooldown_remaining = local_player.dash_timer / local_player.dash_cooldown
                    fill_width = int(dash_bar_width * (1 - cooldown_remaining))
                    if fill_width > 0:
                        pygame.draw.rect(self.screen, (80, 80, 100), (dash_ui_x, dash_ui_y, fill_width, dash_bar_height), border_radius=4)
                    cooldown_secs = local_player.dash_timer / 60  # Convert frames to seconds
                    dash_label = f"DASH ({cooldown_secs:.1f}s)"
                    dash_color = (150, 150, 150)
                
                # Draw border
                pygame.draw.rect(self.screen, WHITE, (dash_ui_x, dash_ui_y, dash_bar_width, dash_bar_height), 1, border_radius=4)
                
                # Draw label
                self.draw_text(dash_label, (dash_ui_x + dash_bar_width + 60, dash_ui_y + dash_bar_height // 2), dash_color, size=20)
            
            # --- SPECTATOR UI ---
            elif local_player and not local_player.alive and not self.game_over:
                sw, sh = self.screen.get_size()
                self.draw_text("YOU ARE DEAD", (sw//2, sh//4), RED, size=60)
                if self.spectating_id and self.spectating_id in self.players:
                    target_name = self.players[self.spectating_id].name
                    self.draw_text(f"Spectating: {target_name}", (sw//2, sh - 100), WHITE, size=30)
                    self.draw_text("Click to Switch View", (sw//2, sh - 60), (200, 200, 200), size=24)
            
            # --- GAME OVER UI ---
            if self.game_over:
                sw, sh = self.screen.get_size()
                s = pygame.Surface((sw, sh), pygame.SRCALPHA)
                s.fill((0, 0, 0, 200)) # Dark overlay
                self.screen.blit(s, (0,0))
                
                self.draw_text("GAME OVER", (sw//2, sh//2 - 50), RED, size=80)
                self.draw_text(f"Reached Floor {self.floor_number}", (sw//2, sh//2 + 20), WHITE, size=40)
                
                if self.network.is_host:
                    self.draw_text("Press [R] to Restart", (sw//2, sh//2 + 80), GREEN, size=40)
                    keys = pygame.key.get_pressed()
                    if keys[pygame.K_r]:
                         new_seed = random.randint(10000, 99999)
                         new_color = self._pick_random_floor_color()
                         self.network.send({"type": "GAME_RESTART", "seed": new_seed, "floor_color": new_color})
                         self.game_over = False
                         self.floor_number = 1
                         self.boss_kills_total = 0  # Reset boss kills for difficulty scaling
                         self._start_new_floor(new_seed, new_color, reset_players=True)
                else:
                    self.draw_text("Waiting for Host to Restart...", (sw//2, sh//2 + 80), WHITE, size=30)
            
            # Draw trapdoor if exists and player is in that room (only if alive)
            if local_player and local_player.alive and self.trapdoor and self.trapdoor_room == local_player.current_room_coords:
                td_rect = self.trapdoor.move(-self.camera.x, -self.camera.y)
                pygame.draw.rect(self.screen, (50, 30, 10), td_rect)  # Dark brown trapdoor
                pygame.draw.rect(self.screen, (100, 60, 20), td_rect, 4)  # Brown border
                # Draw ladder pattern
                for i in range(4):
                    y_off = td_rect.top + 15 + i * 15
                    pygame.draw.line(self.screen, (80, 50, 20), (td_rect.left + 10, y_off), (td_rect.right - 10, y_off), 3)
            
            # Level transition popup (only if alive)
            if local_player and self.level_transition_pending and (local_player.alive or self.spectating_id):
                popup_x = 20
                _, sh = self.screen.get_size()
                popup_y = sh - 100
                pygame.draw.rect(self.screen, (30, 30, 40), (popup_x, popup_y, 400, 80), border_radius=10)
                pygame.draw.rect(self.screen, WHITE, (popup_x, popup_y, 400, 80), 2, border_radius=10)
                
                if self.level_transition_requester == self.local_id:
                    if self.local_id in self.level_transition_accepted:
                        popup_text = f"Waiting for others... ({len(self.level_transition_accepted)}/{len(self.players)})"
                    else:
                        popup_text = "Press J to accept level transition"
                else:
                    popup_text = "A player wants to go to the next level!"
                    popup_text2 = "Press J to accept"
                    self.draw_text(popup_text2, (popup_x + 200, popup_y + 55), size=24)
                
                self.draw_text(popup_text, (popup_x + 200, popup_y + 30), size=24)
                
                # Draw Minimap (Toggleable with M) - only if alive
            if local_player and local_player.alive and self.minimap_visible:
                mm_cell_size = 20
                sw, _ = self.screen.get_size()
                mm_start_x = sw - 250
                mm_start_y = 50
                # Draw background
                pygame.draw.rect(self.screen, (20, 20, 20), (mm_start_x, mm_start_y, 220, 220))
                pygame.draw.rect(self.screen, WHITE, (mm_start_x, mm_start_y, 220, 220), 2)
            
                mm_center_x = mm_start_x + 110
                mm_center_y = mm_start_y + 110
                
                # First, draw undiscovered adjacent rooms as gray
                current_room = self.dungeon.get(local_player.current_room_coords)
                if current_room:
                    for dir_name, has_door in current_room.doors.items():
                        if has_door:
                            # Calculate adjacent room coords
                            adj_x, adj_y = local_player.current_room_coords
                            if dir_name == 'N': adj_y -= 1
                            elif dir_name == 'S': adj_y += 1
                            elif dir_name == 'E': adj_x += 1
                            elif dir_name == 'W': adj_x -= 1
                            
                            # Only draw if not visited
                            if (adj_x, adj_y) not in self.visited_rooms and (adj_x, adj_y) in self.dungeon:
                                dx = adj_x - local_player.current_room_coords[0]
                                dy = adj_y - local_player.current_room_coords[1]
                                cx = mm_center_x + dx * mm_cell_size
                                cy = mm_center_y + dy * mm_cell_size
                                if mm_start_x < cx < mm_start_x + 220 and mm_start_y < cy < mm_start_y + 220:
                                    pygame.draw.rect(self.screen, GRAY, (cx - mm_cell_size//2 + 2, cy - mm_cell_size//2 + 2, mm_cell_size-4, mm_cell_size-4))
                
                # Then draw visited rooms on top
                for (rx, ry) in self.visited_rooms:
                    # Rel to player
                    dx = rx - local_player.current_room_coords[0]
                    dy = ry - local_player.current_room_coords[1]
                    
                    if abs(dx) * mm_cell_size > 100 or abs(dy) * mm_cell_size > 100: continue

                    fill_color = (100, 100, 100)
                    if (rx, ry) == local_player.current_room_coords:
                        fill_color = WHITE
                    elif (rx, ry) in self.dungeon:
                         rtype = self.dungeon[(rx, ry)].type
                         if rtype == ROOM_BOSS: fill_color = RED
                         elif rtype == ROOM_CHEST: fill_color = (255, 215, 0)
                    
                    cx = mm_center_x + dx * mm_cell_size
                    cy = mm_center_y + dy * mm_cell_size
                    
                    if mm_start_x < cx < mm_start_x + 220 and mm_start_y < cy < mm_start_y + 220:
                        pygame.draw.rect(self.screen, fill_color, (cx - mm_cell_size//2 + 2, cy - mm_cell_size//2 + 2, mm_cell_size-4, mm_cell_size-4))
                
                # Draw Player Dots
                for p in self.players.values():
                    if hasattr(p, 'alive') and not p.alive:
                        continue
                    prx, pry = p.current_room_coords
                    dx = prx - local_player.current_room_coords[0]
                    dy = pry - local_player.current_room_coords[1]
                    
                    pcx = mm_center_x + dx * mm_cell_size
                    pcy = mm_center_y + dy * mm_cell_size
                    
                    if mm_start_x < pcx < mm_start_x + 220 and mm_start_y < pcy < mm_start_y + 220:
                        p_color = p.name_color if hasattr(p, 'name_color') else WHITE
                        pygame.draw.circle(self.screen, p_color, (int(pcx), int(pcy)), 4)

                # Weapon Heat Bar (Minigun) - only if alive
                if local_player and local_player.alive and local_player.weapon.name == "Minigun":
                    heat_pct = local_player.weapon.current_heat / local_player.weapon.max_heat
                    bar_width = 200
                    bar_height = 20
                    sw, sh = self.screen.get_size()
                    bar_x = sw - bar_width - 20
                    bar_y = sh - 60
                    
                    # Background
                    pygame.draw.rect(self.screen, BLACK, (bar_x, bar_y, bar_width, bar_height))
                    pygame.draw.rect(self.screen, WHITE, (bar_x, bar_y, bar_width, bar_height), 2)
                    
                    # Fill
                    fill_width = int(bar_width * heat_pct)
                    color = ORANGE if not local_player.weapon.overheated else RED
                    if fill_width > 0:
                         pygame.draw.rect(self.screen, color, (bar_x, bar_y, fill_width, bar_height))
                    
                    # Text
                    label = "OVERHEATED!" if local_player.weapon.overheated else "HEAT"
                    txt = self.font.render(label, True, WHITE)
                    self.screen.blit(txt, (bar_x, bar_y - 25))

            # Pause menu overlay (non-pausing, just UI)
            if self.pause_menu_open and self.state == "GAME":
                sw, sh = self.screen.get_size()
                overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 160))
                self.screen.blit(overlay, (0, 0))

                self.draw_text("PAUSED", (sw // 2, sh // 2 - 120), WHITE, size=60)

                layout = self._get_pause_menu_layout()
                mouse_pos = pygame.mouse.get_pos()
                mouse_click = pygame.mouse.get_pressed()[0]

                # Fullscreen Toggle Button
                fs_rect = layout["Fullscreen"]
                hovered = fs_rect.collidepoint(mouse_pos)
                pygame.draw.rect(self.screen, (70, 70, 90) if hovered else (40, 40, 60), fs_rect, border_radius=8)
                pygame.draw.rect(self.screen, WHITE, fs_rect, 2, border_radius=8)
                label = "Exit Fullscreen" if self.fullscreen else "Enter Fullscreen"
                self.draw_text(label, fs_rect.center, size=24)

                # Sliders
                self._draw_volume_slider(layout["GameVolume"], "Game", self.game_volume)
                self._draw_volume_slider(layout["MusicVolume"], "Music", self.music_volume)

                # Quit Button
                q_rect = layout["Quit"]
                q_hovered = q_rect.collidepoint(mouse_pos)
                pygame.draw.rect(self.screen, (70, 70, 90) if q_hovered else (40, 40, 60), q_rect, border_radius=8)
                pygame.draw.rect(self.screen, WHITE, q_rect, 2, border_radius=8)
                self.draw_text("Quit to Menu", q_rect.center, size=24)

                # Interaction
                if mouse_click and not self.pause_click_held:
                    if hovered:
                        self.pause_click_held = True
                        self._play_sfx("click")
                        self._apply_fullscreen(not self.fullscreen)
                    elif q_hovered:
                        self.pause_click_held = True
                        self._play_sfx("click")
                        self._quit_to_menu()
                    elif layout["GameVolume"].collidepoint(mouse_pos):
                        self.dragging_game = True
                    elif layout["MusicVolume"].collidepoint(mouse_pos):
                        self.dragging_music = True
                elif not mouse_click:
                    self.pause_click_held = False

        pygame.display.flip()


    def _line_circle_collision(self, line_start, line_end, circle_center, radius):
        """Check if a line segment intersects with a circle"""
        # Vector from line start to circle center
        to_circle = pygame.math.Vector2(circle_center) - pygame.math.Vector2(line_start)
        # Vector from line start to line end
        line_vec = pygame.math.Vector2(line_end) - pygame.math.Vector2(line_start)
        line_length = line_vec.length()
        
        if line_length == 0:
            return to_circle.length() <= radius
        
        line_vec = line_vec.normalize()
        
        # Project circle center onto line
        projection_length = to_circle.dot(line_vec)
        projection_length = max(0, min(line_length, projection_length))
        
        # Find closest point on line to circle center
        closest_point = pygame.math.Vector2(line_start) + line_vec * projection_length
        
        # Check distance from circle center to closest point
        distance = (pygame.math.Vector2(circle_center) - closest_point).length()
        return distance <= radius

    def draw_text(self, text, center_pos, color=WHITE, size=36):
        font = pygame.font.Font(None, size)
        surface = font.render(text, True, color)
        rect = surface.get_rect(center=center_pos)
        self.screen.blit(surface, rect)

    def _get_name_input_rect(self):
        sw, sh = self.screen.get_size()
        w = min(520, sw - 80)
        h = 60
        x = sw // 2 - w // 2
        y = sh // 2 - 70
        return pygame.Rect(x, y, w, h)

import random # Needed for mock id

if __name__ == "__main__":
    game = Game()
    game.run()
    pygame.quit()
    sys.exit()
