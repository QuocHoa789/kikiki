#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate the Roblox API data strings consumed by envlog.luau.

envlog.luau parses __ROBLOX.enums and __ROBLOX.classes:
  enums  : "EnumName:Item=v,Item=v;EnumName:..."
  classes: "Class<super|method,method|event,event|prop,prop;Class<..."

This generator emits the common services/classes and enums that obfuscated
Roblox scripts (Luraph-protected) actually touch, so GetService passes its
validation and the fake environment proxies have the right members.

Output: a Lua module returning { enums = "...", classes = "..." } printed to
stdout (redirect to runtime/roblox_api_data.luau).
"""

ENUMS = {
    "HumanoidStateType": "Climbing,Dead,FallingDown,Flying,Freefall,GettingUp,Jumping,Landed,Running,RunningNoPhysics,Seated,StrafingNoPhysics,Swimming,Physics,None",
    "HumanoidRigType": "R6,R15",
    "HumanoidMoveState": "None,PathfindingJump,PathfindingNoJump,ClickToMove,Controlled",
    "Common": "Blink,Chat,EyesMove,FacialIdle,Idle,Laugh,Point,Roar,Sad,Spawn,Scream,Sneeze,Sneeze2,Die,Heal,JoshNoise,Salute,Shout,Stare,Wave,Jump",
    "KeyCode": "A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z,Zero,One,Two,Three,Four,Five,Six,Seven,Eight,Nine,Space,Return,Escape,Tab,LeftControl,LeftShift,RightShift,Up,Down,Left,Right,F1,F2,F3,F4,F5,Backspace,Enter,Insert,Home,End,PageUp,PageDown,Delete,CapsLock,MouseLeft,MouseRight,MouseMiddle,ButtonX,ButtonY,ButtonA,ButtonB,ButtonL1,ButtonR1,ButtonSelect,ButtonStart,Thumbstick1,Thumbstick2,Unknown",
    "UserInputType": "Keyboard,MouseButton1,MouseButton2,MouseButton3,MouseMovement,MouseWheel,Touch,Gamepad1,Gamepad2,Gamepad3,Gamepad4,TenFootInterface",
    "Notification": "Default,Skill,FreeItem,Item,Breakage,InsecureConnection,SkippedTeleport",
    "CoreGuiType": "PlayerList,Health,Backpack,EmotesMenu,Chat,All",
    "Alignment": "Left,Center,Right",
    "FillDirection": "Horizontal,Vertical",
    "FontSize": "Size8,Size9,Size10,Size11,Size12,Size14,Size18,Size24,Size36,Size48,Size64,Size96",
    "Font": "Legacy,Arial,ArialBold,SourceSans,SourceSansBold,SourceSansSemibold,SourceSansLight,SourceSansItalic,Bodoni,Garamond,Cartoon,Code,Highway,SciFi,Arcade,Fantasy,Antique,NotoSans,Gotham,GothamMedium,GothamBold,GothamBlack,AmaticSC,Bangers,Creepster,DenkOne,Fondamento,FredokaOne,GrenzeGotisch,IndieFlower,JosefinSans,Jura,Kalam,LuckiestGuy,Merriweather,Michroma,Nunito,Oswald,PatrickHand,PermanentMarker,Roboto,RobotoCondensed,RobotoMono,Rubik,Sarpanch,SpecialElite,TitilliumWeb,Ubuntu",
    "TextXAlignment": "Left,Center,Right",
    "TextYAlignment": "Top,Center,Bottom",
    "EasingStyle": "Linear,Sine,Back,Quad,Quart,Quint,Bounce,Elastic,Exponential,Circular,Cubic",
    "EasingDirection": "In,Out,InOut",
    "ActuatorType": "None,Motor,Servo",
    "Material": "Plastic,Wood,Slate,Concrete,CorrodedMetal,DiamondPlate,Foil,Grass,Ice,Marble,Granite,Brick,Pebble,Sand,Fabric,SmoothPlastic,Metal,WoodPlanks,Cobblestone,Air,Water,Rock,Glacier,Snow,Sandstone,Neon,ForceField",
    "AnimationPriority": "Idle,Movement,Action,Core",
    "OriginType": "Center,Bottom",
    "Axis": "X,Y,Z",
    "RigType": "R6,R15",
}

# per class: (super, methods, events, properties)
CLASSES = {
    "Instance": ("", "GetChildren,GetDescendants,FindFirstChild,FindFirstChildOfClass,FindFirstChildWhichIsA,WaitForChild,IsA,GetFullName,Destroy,Clone,ClearAllChildren,GetPropertyChangedSignal,GetAttribute,SetAttribute,AddChild", "AncestryChanged,ChildAdded,ChildRemoved,Destroying,Changed", "Name,Parent,ClassName,Archivable,DataCost"),
    "DataModel": ("Instance", "GetService,FindService,IsLoaded,Load,FindFirstChildOfClass,GetObjects,HttpGet,HttpPost,PlaceId,GameId,JobId", "Loaded", "Workspace,Players,Lighting,PlaceId,GameId,JobId,CreatorId,CreatorType,MessageId"),
    "Workspace": ("Model", "GetRealPhysicsFloats,BreakJoints,MakeJoints", "CurrentCamera,FilteringEnabled,StreamingEnabled,Terrain,DistributedGameTime", "Gravity,GlobalWind,StreamingEnabled,Parent"),
    "Players": ("Instance", "GetPlayers,GetPlayerFromCharacter,GetUserIdFromNameAsync,GetNameFromUserIdAsync,CreateLocalPlayer,GetChildren,FindFirstChild", "PlayerAdded,PlayerRemoving,CharacterAutoLoads", "LocalPlayer,MaxPlayers,PreferredPlayer,RespawnTime,BubbleChat,CharacterAutoLoads"),
    "Player": ("Instance", "Kick,LoadCharacter,GetJoinData,GetFriendsOnline,GetMouse", "CharacterAdded,CharacterRemoving,Chatted,MouseEnter,MouseLeave,Idle", "Character,UserId,DisplayName,Name,Team,TeamColor,Neutral,CharacterAppearanceLoaded"),
    "Humanoid": ("Instance", "MoveTo,Move,Jump,GetState,ChangeState,SetStateEnabled,TakeDamage,PlayEmote,GetStateEnabled,AddAccessory", "Died,StateChanged,Running,Jumping,Seated,FreedFromMemory,MoveFinished,AnimationPlayed,Touched", "Health,MaxHealth,WalkSpeed,JumpPower,HipHeight,AutoRotate,PlatformStand,DisplayName,HealthDisplayDistance,MoveDirection,SeatPart,Jump"),
    "RunService": ("Instance", "IsStudio,IsServer,IsClient,IsRunMode,IsEdit,IsRemote,BindToRenderStep,UnbindFromRenderStep", "Heartbeat,Stepped,RenderStepped,PreRender,PostSimulation,PreSimulation", ""),
    "TweenService": ("Instance", "Create,GetValue", "", ""),
    "HttpService": ("Instance", "JSONEncode,JSONDecode,GetAsync,PostAsync,RequestAsync,GetSecret,GenerateGUID,UrlEncode,HttpPostAsync", "", "HttpEnabled,AutoRetry,MaxRetries"),
    "UserInputService": ("Instance", "IsKeyDown,IsKeyPressed,IsGamepadButtonDown,GetGamepadState,GetMouseLocation,GetMouseButtonsPressed", "InputBegan,InputEnded,InputChanged,JumpRequest,TextBoxFocused", "TouchEnabled,KeyboardEnabled,MouseEnabled,MouseBehavior,GamepadEnabled,ModalEnabled,VREnabled,NavGamepadEnabled"),
    "StarterGui": ("Instance", "SetCore,SetCoreGuiEnabled,GetCore,GetCoreGuiEnabled,ResetPlayerGuiOnSpawn,AddCoreScript,AddCore", "", "ScreenInsets,ProcessNotifications"),
    "CoreGui": ("Instance", "GetChildren,FindFirstChild,SetCore,SetCoreGuiEnabled", "", ""),
    "ReplicatedStorage": ("Instance", "GetChildren,FindFirstChild,WaitForChild", "", ""),
    "ServerStorage": ("Instance", "GetChildren,FindFirstChild,WaitForChild", "", ""),
    "StarterPlayer": ("Instance", "", "", "CharacterWalkSpeed,EnableMouseLockOption,CameraMaxZoomDistance,CameraMinZoomDistance"),
    "Lighting": ("Instance", "GetMinutesAfterMidnight,SetMinutesAfterMidnight", "LightingChanged,ClockTime", "Brightness,Ambient,ColorShift_Top,OutdoorAmbient,ClockTime,GeographicLatitude,GlobalShadows,TimeOfDay,FogEnd,FogStart,FogColor,ExposureCompensation"),
    "Tween": ("Instance", "Play,Cancel", "Completed", "Instance,TweenInfo"),
    "TweenInfo": ("", "", "", "Time,EasingStyle,EasingDirection,RepeatCount,Reverses,DelayTime"),
    "ScreenGui": ("Instance", "", "", "Name,Enabled,ResetOnSpawn,IgnoreGuiInset,DisplayOrder,ZIndexBehavior,Parent"),
    "Frame": ("Instance", "", "", "Size,Position,BackgroundColor3,BackgroundTransparency,BorderSizePixel,BorderColor3,Visible,Parent,AnchorPoint,Rotation,ZIndex,AutomaticSize,ClipsDescendants"),
    "TextLabel": ("Instance", "", "", "Text,Size,Position,TextColor3,TextSize,Font,BackgroundTransparency,BackgroundColor3,Visible,Parent,TextWrapped,TextScaled,RichText,TextXAlignment,TextYAlignment,LineHeight,ZIndex,Rotation,AnchorPoint,MaxVisibleGraphemes"),
    "TextButton": ("Instance", "", "Activated,MouseButton1Click,MouseButton1Down,MouseButton1Up,MouseEnter,MouseLeave", "Text,Size,Position,TextColor3,TextSize,Font,BackgroundColor3,BackgroundTransparency,Visible,Parent,AutoButtonColor,TextWrapped,TextScaled,Modal,Selected,ZIndex"),
    "TextBox": ("Instance", "", "Focused,FocusLost,ReturnPressedFromEnter", "Text,PlaceholderText,PlaceholderColor3,ClearTextOnFocus,MultiLine,TextEditable,Size,Position,TextColor3,Font,BackgroundColor3,BackgroundTransparency,Visible,Parent,TextWrapped,TextScaled"),
    "ImageLabel": ("Instance", "", "", "Image,ImageColor3,ImageTransparency,Size,Position,BackgroundTransparency,Visible,Parent,ScaleType,ZIndex,Rotation,ResampleMode"),
    "ImageButton": ("Instance", "", "Activated,MouseButton1Click,MouseEnter,MouseLeave", "Image,Size,Position,BackgroundTransparency,Visible,Parent,AutoButtonColor,ZIndex"),
    "UIGradient": ("Instance", "", "", "Color,Rotation,Offset,Transparency,Enabled,Parent"),
    "UIListLayout": ("Instance", "", "", "FillDirection,Padding,SortOrder,HorizontalAlignment,VerticalAlignment,Parent"),
    "UICorner": ("Instance", "", "", "CornerRadius,Parent"),
    "UIStroke": ("Instance", "", "", "Color,Thickness,Transparency,ApplyStrokeMode,Enabled,Parent,LineJoinMode"),
    "BillboardGui": ("Instance", "", "", "Size,StudsOffset,ExtentsOffset,AlwaysOnTop,Enabled,Adornee,MaxDistance,LightInfluence,Parent"),
    "SurfaceGui": ("Instance", "", "", "CanvasSize,Face,AlwaysOnTop,Enabled,LightInfluence,Parent"),
    "Part": ("Instance", "CanSetNetworkOwnership,GetMass,ApplyImpulse,ApplyAngularImpulse", "Touched,TouchEnded", "Size,Position,CFrame,Color,BrickColor,Material,Transparency,Anchored,CanCollide,Locked,Velocity,AssemblyLinearVelocity,Shape,Size,Orientation,Reflectance,Massless,Parent"),
    "Model": ("Instance", "GetBoundingBox,GetExtentsSize,GetPrimaryPartCFrame,MoveTo,SetPrimaryPartCFrame,BreakJoints,MakeJoints", "", "PrimaryPart,WorldPivot,Parent"),
    "MeshPart": ("Part", "", "", "MeshId,TextureID,TextureID"),
    "SpecialMesh": ("Instance", "", "", "MeshType,Scale,MeshId,TextureId,VertexColor,Parent"),
    "Sound": ("Instance", "Play,Pause,Resume,Stop,PlayOnRemove", "Ended,Loaded,DidLoop,Paused,Played,Stopped", "SoundId,Volume,Pitched,PlaybackSpeed,Looped,Playing,TimePosition,IsLoaded,IsPlaying,IsPaused,RollOffMode,Parent,SoundGroup"),
    "SoundGroup": ("Instance", "", "", "Volume,Name,Parent"),
    "RemoteEvent": ("Instance", "FireServer,FireClient,FireAllClients,IsA", "OnClientEvent,OnServerEvent", "Parent"),
    "RemoteFunction": ("Instance", "InvokeServer,InvokeClient,InvokeAllClients", "OnClientInvoke,OnServerInvoke", "Parent"),
    "Script": ("Instance", "", "", "Source,Enabled,Disabled,Parent,RunContext"),
    "LocalScript": ("Instance", "", "", "Source,Enabled,Disabled,Parent"),
    "ModuleScript": ("Instance", "", "", "Source,Parent,Name"),
    "HumanoidRootPart": ("Part", "", "", "Size,CFrame,Velocity,Parent"),
    "Accessory": ("Instance", "", "", "AccessoryType,AttachmentPoint,Parent"),
    "Backpack": ("Instance", "", "", "Parent"),
    "Tool": ("Instance", "Activate,Deactivate,Equip,Unequip", "Activated,Deactivated,Equipped,Unequipped", "Enabled,Grip,GripForward,GripPos,GripRight,GripUp,RequiresHandle,CanBeDropped,Parent,ToolTip"),
    "Ray": ("", "", "", "Origin,Direction,Unit,Magnitude,ClosestPoint,Distance"),
    "Path": ("Instance", "ComputeAsync,GetWaypoints", "PathCompleted,PathFailed,Blocked,Unblocked", "WaypointSpacing,AgentRadius,AgentHeight,AgentCanJump,AgentCanClimb,AgentTrusts,Parent"),
    "PathfindingService": ("Instance", "CreatePath,FindPathAsync", "", ""),
    "Chat": ("Instance", "Chat,FilterStringAsync,FilterStringForBroadcast,ShouldDeliverGameChatMessage", "Chatted", "BubbleChatEnabled,LoadStringChatPermissions"),
    "Teams": ("Instance", "GetTeams", "", "Parent"),
    "Team": ("Instance", "GetPlayers,GetPlayersOnTeam", "PlayerAdded,PlayerRemoved", "TeamColor,AutoAssignable,Name,Parent"),
    "ProximityPrompt": ("Instance", "", "Triggered,TriggerEnded,PromptButtonHoldBegan,PromptButtonHoldEnded", "ActionText,ObjectText,KeyboardKeyCode,GamepadKeyCode,HoldDuration,MaxActivationDistance,RequiresLineOfSight,Enabled,Style,Parent"),
    "ClickDetector": ("Instance", "", "MouseClick,MouseClickConnect,RightMouseClick,MouseHoverEnter,MouseHoverLeave", "MaxActivationDistance,CursorIcon,Parent"),
    "Random": ("", "NextInteger,NextNumber,NextUnitVector,Clone", "", ""),
    "Vector3": ("", "", "", "X,Y,Z,Magnitude,Unit"),
    "Vector2": ("", "", "", "X,Y,Magnitude,Unit"),
    "CFrame": ("", "GetComponents,ToWorldSpace,ToObjectSpace,PointToWorldSpace,PointToObjectSpace,VectorToWorldSpace,VectorToObjectSpace,Inverse,Lerp,ToEulerAnglesXYZ,ToAxisAngle,LookVector,UpVector,RightVector,XVector,YVector,ZVector,Position", "", "Position,LookVector,UpVector,RightVector,X,Y,Z"),
    "Color3": ("", "ToHSV,Lerp", "", "R,G,B"),
    "ColorSequence": ("", "", "", "Keypoints"),
    "NumberSequence": ("", "", "", "Keypoints"),
    "NumberRange": ("", "", "", "Min,Max"),
    "UDim2": ("", "", "", "X,Y,XOffset,YOffset,Width,Height"),
    "UDim": ("", "", "", "Scale,Offset"),
    "BrickColor": ("", "", "", "Name,Number,Color"),
    "Font": ("", "", "", "Name,Weight,Style,Family,Bold"),
    "EnumItem": ("", "", "", "Name,Value,EnumType"),
    "Path2DControlPoint": ("", "", "", "Position"),
    "Attachment": ("Instance", "GetAxis,GetOrientation,GetPosition,SetAxis,SetOrientation,SetPosition,GetWorldPosition,GetWorldAxis,GetWorldOrientation", "", "Position,Orientation,Axis,SecondaryAxis,Visible,WorldPosition,WorldOrientation,WorldAxis,Parent"),
    "Camera": ("Instance", "GetPartsObscuringTarget,ScreenPointToRay,ViewportPointToRay,WorldToScreenPoint,WorldToViewportPoint,ScreenToViewportPoint,ViewportToScreenPoint", "", "CFrame,FieldOfView,CameraType,CameraSubject,Focus,MaxZoomDistance,MinZoomDistance,ViewportSize,HeadLocked"),
}


def main():
    enums_s = ";".join(f"{n}:{items}" for n, items in ENUMS.items())
    classes_s = ";".join(
        f"{name}<{super}|{fns}|{evs}|{props}"
        for name, (super, fns, evs, props) in CLASSES.items()
    )

    def lua_str(s):
        for lvl in range(0, 6):
            eq = "=" * lvl
            if f"]{eq}]" not in s:
                return f"[{eq}[{s}]{eq}]"
        raise ValueError

    print("--!nocheck")
    print("-- generated by gen_roblox_data.py: Roblox API data for envlog.luau")
    print("-- (replaces the broken/truncated roblox_api.luau fragment)")
    print("return {")
    print(f"\tenums = {lua_str(enums_s)},")
    print(f"\tclasses = {lua_str(classes_s)},")
    print("}")


if __name__ == '__main__':
    main()
